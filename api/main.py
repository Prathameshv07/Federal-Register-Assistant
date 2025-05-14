import asyncio
import json
import uuid
import logging
import os
import sys
from datetime import datetime
from typing import Dict, List, Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
import uvicorn

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.agent import Agent
from db_connector import get_database_stats, query_documents
from pipeline.main import run_single_day

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("api")

# Create FastAPI app
app = FastAPI(
    title="Federal Register Assistant",
    description="RAG-enabled Federal Register document search and analysis",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For demo purposes
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Jinja2 templates
templates = Jinja2Templates(directory="static")

# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

# Initialize agent (lazy loading)
_agent = None

def get_agent():
    global _agent
    if _agent is None:
        _agent = Agent()
    return _agent

# Connection manager for WebSockets
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.connection_histories: Dict[str, List[Dict[str, Any]]] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self.active_connections[session_id] = websocket
        if session_id not in self.connection_histories:
            self.connection_histories[session_id] = []

    def disconnect(self, session_id: str):
        if session_id in self.active_connections:
            del self.active_connections[session_id]

    def get_history(self, session_id: str) -> List[Dict[str, Any]]:
        if session_id not in self.connection_histories:
            self.connection_histories[session_id] = []
        return self.connection_histories[session_id]

    def add_to_history(self, session_id: str, message: Dict[str, Any]):
        if session_id not in self.connection_histories:
            self.connection_histories[session_id] = []
        self.connection_histories[session_id].append(message)

# Initialize connection manager
manager = ConnectionManager()

# API endpoints
@app.get("/", response_class=HTMLResponse)
async def get_home(request: Request):
    """Serve the home page HTML interface"""
    return templates.TemplateResponse("home.html", {"request": request})

@app.get("/chat", response_class=HTMLResponse)
async def get_chat(request: Request):
    """Serve the chat interface HTML"""
    return templates.TemplateResponse("chat.html", {"request": request})

@app.get("/api/health")
async def health_check():
    """API health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/api/database/stats")
async def get_stats():
    """Get statistics about the Federal Register database"""
    stats = await get_database_stats()
    return stats

@app.get("/api/database/update")
async def update_database(date: Optional[str] = None):
    """Trigger a database update for a specific date"""
    try:
        result = await run_single_day(date)
        return result
    except Exception as e:
        logger.error(f"Error updating database: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error updating database: {str(e)}")

@app.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for chat interface"""
    session_id = str(uuid.uuid4())
    await manager.connect(websocket, session_id)
    agent = get_agent()
    
    try:
        # Send welcome message
        await websocket.send_json({
            "type": "assistant_message",
            "content": "Welcome! Ask me anything about federal regulations, executive orders, or other government documents.",
            "id": 0,
            "metadata": {
                "query_time": 0,
                "tools_used": []
            }
        })
        
        # Track most recently used tools for persistent display
        last_tools_used = []
        
        # Get database stats for welcome
        try:
            stats = await get_database_stats()
            if stats.get("total_documents", 0) > 0:
                stats_message = (
                    f"I have access to {stats['total_documents']} Federal Register documents "
                    f"from {stats['date_range']['min']} to {stats['date_range']['max']}."
                )
                
                # Use get_database_statistics as the tool for this message
                last_tools_used = ["get_database_statistics"]
                
                await websocket.send_json({
                    "type": "assistant_message",
                    "content": stats_message,
                    "id": 0,
                    "metadata": {
                        "query_time": 0,
                        "tools_used": last_tools_used
                    }
                })
        except Exception as e:
            logger.error(f"Error getting database stats: {str(e)}")
        
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            message_data = json.loads(data)
            
            if message_data.get("type") == "user_message":
                user_query = message_data.get("content", "")
                message_id = message_data.get("id", len(manager.get_history(session_id)) // 2)
                
                # Add user message to history
                user_message = {"role": "user", "content": user_query}
                manager.add_to_history(session_id, user_message)
                
                # Send "thinking" message
                await websocket.send_json({
                    "type": "thinking",
                    "id": message_id
                })
                
                # Process query with streaming for better user experience
                try:
                    # Use non-streaming for simplicity in this demo
                    # In production, you would use the streaming version
                    history = [msg for msg in manager.get_history(session_id)[:-1]]  # Exclude the current query
                    response = await agent.generate_response(user_query, history, session_id)
                    
                    # Add assistant response to history
                    manager.add_to_history(session_id, response)
                    
                    # Ensure metadata exists
                    if "metadata" not in response:
                        response["metadata"] = {
                            "query_time": 0,
                            "tools_used": last_tools_used  # Use previously tracked tools
                        }
                    
                    # Update the last tools used if present in the current response
                    if response["metadata"].get("tools_used") and len(response["metadata"]["tools_used"]) > 0:
                        last_tools_used = response["metadata"]["tools_used"]
                    
                    # Send response to client
                    await websocket.send_json({
                        "type": "assistant_message",
                        "content": response.get("content", ""),
                        "metadata": response.get("metadata", {}),
                        "id": message_id
                    })
                    
                    # Send query suggestions if available
                    try:
                        suggestions_response = await agent.execute_tool([{
                            "id": "suggest-1",
                            "function": {
                                "name": "suggest_related_queries",
                                "arguments": json.dumps({"current_query": user_query})
                            }
                        }])
                        
                        if suggestions_response and len(suggestions_response) > 0:
                            suggestions_content = json.loads(suggestions_response[0].get("content", "{}"))
                            suggestions = suggestions_content.get("suggestions", [])
                            
                            if suggestions:
                                await websocket.send_json({
                                    "type": "suggestions",
                                    "suggestions": suggestions,
                                    "id": message_id
                                })
                    except Exception as e:
                        logger.error(f"Error generating suggestions: {str(e)}")
                    
                except Exception as e:
                    logger.error(f"Error generating response: {str(e)}")
                    await websocket.send_json({
                        "type": "assistant_message",
                        "content": f"I'm sorry, I encountered an error: {str(e)}. Please try rephrasing your question.",
                        "id": message_id,
                        "metadata": {
                            "query_time": 0,
                            "tools_used": last_tools_used  # Keep existing tools
                        }
                    })
    
    except WebSocketDisconnect:
        logger.info(f"Client disconnected: {session_id}")
        manager.disconnect(session_id)
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        manager.disconnect(session_id)
        try:
            await websocket.send_json({
                "type": "assistant_message",
                "content": f"I'm sorry, I encountered a system error. Please try refreshing the page.",
                "id": 0,
                "metadata": {
                    "query_time": 0,
                    "tools_used": last_tools_used  # Keep existing tools
                }
            })
        except:
            pass

if __name__ == "__main__":
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True) 