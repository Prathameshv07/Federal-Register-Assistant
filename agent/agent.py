import json
import re
import asyncio
import logging
from typing import Dict, Any, List, Optional, Union
import aiohttp
import os
import sys
from datetime import datetime, timedelta

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db_connector import query_documents, get_database_stats, log_chat

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("agent")

class Agent:
    def __init__(self, model_name="qwen2.5:1.5b-instruct-q4_K_M", ollama_url=None):
        """Initialize the agent with model configuration"""
        self.model_name = model_name
        self.ollama_url = ollama_url or os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "query_federal_register",
                    "description": "Search the Federal Register database for documents matching specific criteria",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "keywords": {
                                "type": "string",
                                "description": "Keywords to search for in titles and abstracts"
                            },
                            "document_type": {
                                "type": "string",
                                "description": "Type of document (e.g., 'executive_order', 'notice', 'rule', 'proposed_rule', 'presidential_document')"
                            },
                            "start_date": {
                                "type": "string",
                                "description": "Start date in YYYY-MM-DD format"
                            },
                            "end_date": {
                                "type": "string",
                                "description": "End date in YYYY-MM-DD format"
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of results to return",
                                "default": 10
                            }
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_database_statistics",
                    "description": "Get statistics about the Federal Register database",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "suggest_related_queries",
                    "description": "Generate suggestions for related queries based on the current query",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "current_query": {
                                "type": "string",
                                "description": "The current user query"
                            }
                        },
                        "required": ["current_query"]
                    }
                }
            }
        ]
        
        self.system_prompt = """You are a helpful Federal Register Assistant with access to a database of federal regulations, executive orders, and other government documents. Your responses should be informative, conversational, and helpful.

When users ask about federal regulations, executive orders, or other government documents, use the query_federal_register tool to search the database.
You can search by keywords, document type, and date range.

Available document types include:
- executive_order (Executive Orders)
- notice (Notices)
- rule (Rules)
- proposed_rule (Proposed Rules)
- presidential_document (Presidential Documents)

CONVERSATION STYLE GUIDELINES:
1. Be warm, personable, and conversational - avoid robotic or formulaic responses
2. Use natural language variations and avoid repeating the same phrases
3. Express thoughtfulness through language markers like "Let me see," "I'm looking into that," or "That's an interesting question"
4. Include brief context and background when discussing regulations
5. When appropriate, add insights about the significance or impact of particular documents
6. Be concise but thorough - include relevant details without overwhelming the user
7. Use light transition phrases between topics like "Regarding your question," "As for," or "Moving to"
8. Show enthusiasm for helping with phrases like "I'd be happy to," "I can certainly help with that," or "Great question"

IMPORTANT INSTRUCTIONS FOR HIGH-QUALITY RESPONSES:
1. Think step-by-step when analyzing queries and formulating responses.
2. Structure your responses clearly with a brief introduction, detailed findings, and a concise summary.
3. When you don't have enough information, ask clarifying questions before searching.
4. If search results return empty, explain the issue clearly and suggest alternative queries.
5. Always specify the source of information (document number, publication date).
6. Handle dates intelligently - if users mention "this year", "last month", etc., convert to actual date ranges.
7. Never list results in a mechanical format like [{ "doc_number": "X" }] - instead, present information in a natural, conversational paragraph format.
8. When discussing executive orders, include a brief note about their purpose or significance when available.

Few-shot examples:

User: "What are the latest executive orders?"
Assistant thinking: I need to search for recent executive orders. I'll use the query_federal_register tool with document_type set to "executive_order" and sort by recency. I'll present the results conversationally.
Assistant: "I've found some recent executive orders for you. Executive Order 13507 from August 14th, 2023 establishes a new program to address climate change. Earlier, on July 28th, Executive Order 13609 was issued directing government agencies on sustainable development. There's also Executive Order 13456 from June 17th prohibiting single-use plastics in federal facilities. Would you like me to provide more details about any of these?"

User: "Tell me about climate change regulations"
Assistant thinking: This query is about climate change regulations. I should search for documents with keywords related to climate change. I'll present the results conversationally and add context.
Assistant: "There have been several important regulations related to climate change recently. I found a rule from the EPA published on March 15th, 2023 that establishes new emissions standards for power plants. There's also a proposed rule from October 2nd that would require larger companies to disclose their climate-related financial risks. The most recent executive order addressing climate change is EO-13507 from August, which creates a new federal program for climate adaptation. Is there a specific aspect of climate regulation you're interested in?"

User: "Are there any executive orders about healthcare from last month?"
Assistant thinking: I need to determine what "last month" means relative to the current date, then search specifically for executive orders related to healthcare within that timeframe.
Assistant: "I've looked through executive orders from last month (March 2023), and I don't see any that specifically focus on healthcare. The most recent healthcare-related executive order I can find is from February 15th, 2023, which addresses prescription drug pricing. Would you like me to search for healthcare regulations more broadly, or perhaps look at a different time period?"

Only use tools when necessary. If you can answer directly, do so.
Format your responses in a clear, conversational manner.
If the data is not found or the database returns no results, explain that to the user politely and suggest alternative queries.

Important: Do not make up information. Only provide information that is available in the database.
Also, do not reveal the names of the tools you are using to the user.
"""

    async def _fix_json(self, json_str: str) -> str:
        """Fix common JSON errors in LLM outputs"""
        # Ensure we're working with a string
        if not isinstance(json_str, str):
            try:
                # Try to convert to string if it's not already
                json_str = str(json_str)
            except:
                return "{}"
            
        # Remove any markdown formatting
        json_str = re.sub(r'```(?:json)?([^`]+)```', r'\1', json_str).strip()
        
        # Fix missing quotes around property names
        json_str = re.sub(r'(\s*?)(\w+)(:)', r'\1"\2"\3', json_str)
        
        # Fix single quotes to double quotes
        json_str = json_str.replace("'", '"')
        
        # Fix trailing commas
        json_str = re.sub(r',\s*}', '}', json_str)
        json_str = re.sub(r',\s*]', ']', json_str)
        
        return json_str

    async def execute_tool(self, tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Execute the tool calls and return the results"""
        results = []
        
        for tool_call in tool_calls:
            function = tool_call.get("function", {})
            name = function.get("name")
            arguments_json = function.get("arguments", "{}")
            
            # Fix potential JSON issues
            fixed_json = await self._fix_json(arguments_json)
            
            try:
                arguments = json.loads(fixed_json)
            except json.JSONDecodeError as e:
                logger.error(f"JSON parse error in arguments: {str(e)}, raw: {arguments_json}")
                arguments = {}
            
            try:
                if name == "query_federal_register":
                    # Execute the database query
                    documents = await query_documents(
                        keywords=arguments.get("keywords"),
                        document_type=arguments.get("document_type"),
                        start_date=arguments.get("start_date"),
                        end_date=arguments.get("end_date"),
                        limit=arguments.get("limit", 10)
                    )
                    
                    # Ensure document_type is never null in the response
                    for doc in documents:
                        if doc.get("document_type") is None:
                            doc["document_type"] = "unspecified"
                        
                        # Make sure the document type is set to a standard value if possible
                        if doc.get("document_type") == "unspecified":
                            # Try to infer document type from title or other fields
                            title = doc.get("title", "").lower()
                            if "executive order" in title or title.startswith("eo"):
                                doc["document_type"] = "executive_order"
                            elif "notice" in title:
                                doc["document_type"] = "notice"
                            elif "rule" in title and "proposed" in title:
                                doc["document_type"] = "proposed_rule"
                            elif "rule" in title:
                                doc["document_type"] = "rule"
                    
                    results.append({
                        "tool_call_id": tool_call.get("id"),
                        "role": "tool",
                        "name": name,
                        "content": json.dumps(documents)
                    })
                
                elif name == "get_database_statistics":
                    # Get database stats
                    stats = await get_database_stats()
                    
                    results.append({
                        "tool_call_id": tool_call.get("id"),
                        "role": "tool",
                        "name": name,
                        "content": json.dumps(stats)
                    })
                
                elif name == "suggest_related_queries":
                    # Generate related queries
                    current_query = arguments.get("current_query", "")
                    
                    # Simple related query generation (would be improved with LLM in production)
                    if "executive" in current_query.lower():
                        suggestions = [
                            "What are the most recent executive orders?",
                            "Show me executive orders related to healthcare",
                            "How many executive orders were issued last month?"
                        ]
                    elif "climate" in current_query.lower():
                        suggestions = [
                            "What regulations mention climate change?",
                            "Are there any recent rules about carbon emissions?",
                            "Show me climate policies from the EPA"
                        ]
                    else:
                        suggestions = [
                            "What are the latest executive orders?",
                            "Show me recent healthcare regulations",
                            "Find documents related to immigration policy"
                        ]
                    
                    results.append({
                        "tool_call_id": tool_call.get("id"),
                        "role": "tool",
                        "name": name,
                        "content": json.dumps({"suggestions": suggestions})
                    })
            
            except Exception as e:
                logger.error(f"Error executing tool {name}: {str(e)}")
                # Return a more structured error message
                error_message = {
                    "error": str(e),
                    "message": "I encountered an issue when searching the database. Let me try a different approach."
                }
                results.append({
                    "tool_call_id": tool_call.get("id"),
                    "role": "tool",
                    "name": name,
                    "content": json.dumps(error_message)
                })
            
        return results

    async def get_completion(self, messages: List[Dict[str, Any]], stream: bool = False) -> Dict[str, Any]:
        """Get a completion from the LLM"""
        async with aiohttp.ClientSession() as session:
            # Ensure all messages have proper format
            sanitized_messages = []
            for msg in messages:
                # Ensure content is a string
                if "content" in msg and not isinstance(msg["content"], str):
                    try:
                        msg["content"] = str(msg["content"])
                    except:
                        msg["content"] = "Error converting content to string"
                sanitized_messages.append(msg)
            
            payload = {
                "model": self.model_name,
                "messages": sanitized_messages,
                "tools": self.tools,
                "temperature": 0.2,
                "stream": stream
            }
            
            try:
                async with session.post(f"{self.ollama_url}/api/chat", json=payload) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        return {"error": f"Error from LLM API: {error_text}"}
                    
                    if stream:
                        # For streaming, just return the response object
                        return {"stream": response}
                    else:
                        # For non-streaming, parse the JSON response
                        completion = await response.json()
                        return completion
            except Exception as e:
                logger.error(f"Error calling LLM API: {str(e)}")
                return {"error": f"Failed to communicate with LLM: {str(e)}"}

    async def generate_response(self, 
                               user_query: str, 
                               history: List[Dict[str, Any]] = None,
                               session_id: str = "default") -> Dict[str, Any]:
        """Generate a response to the user query, handling tool calls if necessary"""
        if history is None:
            history = []
            
        # Process dates in the query (resolve relative dates)
        processed_query = self._process_dates(user_query)
            
        # Format messages for the LLM
        messages = [{"role": "system", "content": self.system_prompt}] + history
        messages.append({"role": "user", "content": processed_query})
        
        # Get initial response
        start_time = datetime.now()
        response = await self.get_completion(messages)
        
        if "error" in response:
            error_message = {
                "role": "assistant", 
                "content": f"I'm sorry, I encountered an error: {response['error']}. Please try rephrasing your question.",
                "metadata": {
                    "query_time": (datetime.now() - start_time).total_seconds(),
                    "tools_used": []
                }
            }
            await log_chat(session_id, user_query, error_message["content"])
            return error_message
            
        message = response.get("message", {})
        tool_calls = message.get("tool_calls", [])
        
        # Track tools used for analytics
        tools_used = []
        
        # If no tool calls, return the response directly
        if not tool_calls:
            # Add metadata even for direct responses
            if not message.get("metadata"):
                message["metadata"] = {
                    "query_time": (datetime.now() - start_time).total_seconds(),
                    "tools_used": []
                }
            await log_chat(session_id, user_query, message.get("content", ""))
            return message
        
        # Handle tool calls
        tool_results = await self.execute_tool(tool_calls)
        
        # Track which tools were used
        for tool_call in tool_calls:
            function_name = tool_call.get("function", {}).get("name")
            if function_name:
                tools_used.append(function_name)
        
        # Add tool calls and results to messages
        messages.append(message)
        messages.extend(tool_results)
        
        # Get final response with tool results
        final_response = await self.get_completion(messages)
        
        if "error" in final_response:
            error_message = {
                "role": "assistant", 
                "content": f"I'm sorry, I encountered an error: {final_response['error']}. Please try rephrasing your question.",
                "metadata": {
                    "query_time": (datetime.now() - start_time).total_seconds(),
                    "tools_used": tools_used
                }
            }
            await log_chat(session_id, user_query, error_message["content"], tools_used)
            return error_message
        
        final_message = final_response.get("message", {})
        
        # Calculate query time for analytics
        query_time = (datetime.now() - start_time).total_seconds()
        
        # Add metadata for frontend
        final_message["metadata"] = {
            "query_time": query_time,
            "tools_used": tools_used
        }
        
        # Log the interaction
        await log_chat(session_id, user_query, final_message.get("content", ""), tools_used)
        
        return final_message
    
    def _process_dates(self, query: str) -> str:
        """Process relative dates in queries to absolute dates"""
        now = datetime.now()
        
        # Process "this year"
        if "this year" in query.lower():
            year = now.year
            start_date = f"{year}-01-01"
            end_date = f"{year}-12-31"
            query = query.lower().replace("this year", f"from {start_date} to {end_date}")
        
        # Process "last month"
        if "last month" in query.lower():
            last_month = now.month - 1 if now.month > 1 else 12
            year = now.year if now.month > 1 else now.year - 1
            
            # Determine days in month
            if last_month in [4, 6, 9, 11]:
                days = 30
            elif last_month == 2:
                # Check for leap year
                if (year % 4 == 0 and year % 100 != 0) or year % 400 == 0:
                    days = 29
                else:
                    days = 28
            else:
                days = 31
                
            start_date = f"{year}-{last_month:02d}-01"
            end_date = f"{year}-{last_month:02d}-{days}"
            query = query.lower().replace("last month", f"from {start_date} to {end_date}")
        
        return query

    async def generate_streaming_response(self, 
                                        user_query: str, 
                                        history: List[Dict[str, Any]] = None,
                                        session_id: str = "default"):
        """Generate a streaming response (for WebSocket)"""
        if history is None:
            history = []
            
        # Format messages for the LLM
        messages = [{"role": "system", "content": self.system_prompt}] + history
        messages.append({"role": "user", "content": user_query})
        
        # Get initial response (streaming)
        response = await self.get_completion(messages, stream=True)
        
        if "error" in response:
            yield {"role": "assistant", "content": f"I encountered an error: {response['error']}"}
            return
            
        if "stream" not in response:
            yield {"role": "assistant", "content": "Failed to initialize streaming response"}
            return
        
        # Process the stream
        response_stream = response["stream"]
        buffer = ""
        
        try:
            async for line in response_stream.content:
                line = line.decode('utf-8').strip()
                if line.startswith('data: '):
                    data = line[6:]  # Remove 'data: ' prefix
                    if data == '[DONE]':
                        break
                    
                    try:
                        chunk = json.loads(data)
                        
                        # Check for tool calls
                        if 'message' in chunk:
                            message = chunk['message']
                            
                            # If we have tool calls, stop streaming and use the non-streaming approach
                            if 'tool_calls' in message:
                                # Close stream
                                await response_stream.release()
                                
                                # Use non-streaming approach
                                full_response = await self.generate_response(user_query, history, session_id)
                                yield full_response
                                return
                            
                            # Add content to buffer
                            if 'content' in message and message['content']:
                                buffer += message['content']
                                yield {"role": "assistant", "content": buffer, "streaming": True}
                    except json.JSONDecodeError:
                        pass
        
        except Exception as e:
            logger.error(f"Error in streaming response: {str(e)}")
            yield {"role": "assistant", "content": f"Error during streaming: {str(e)}"}
        finally:
            # Ensure stream is closed
            await response_stream.release()
        
        # Log the completed interaction
        await log_chat(session_id, user_query, buffer)
        
        # Return the final complete message
        yield {"role": "assistant", "content": buffer, "streaming": False}

async def test_agent():
    """Test the agent with a sample query"""
    agent = Agent()
    response = await agent.generate_response("What are the latest executive orders?")
    print(json.dumps(response, indent=2))

if __name__ == "__main__":
    asyncio.run(test_agent()) 