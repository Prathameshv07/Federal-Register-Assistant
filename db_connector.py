import os
import json
import asyncio
from typing import List, Dict, Any, Optional
import aiomysql
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("db_connector")

# Database configuration
DB_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "port": int(os.getenv("MYSQL_PORT", 3306)),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", "password"),
    "db": os.getenv("MYSQL_DATABASE", "federal_register"),
    "charset": "utf8mb4",
    "cursorclass": aiomysql.DictCursor
}

async def get_pool():
    """Get a connection pool to the MySQL database"""
    return await aiomysql.create_pool(**DB_CONFIG)

async def init_db():
    """Initialize the database schema if it doesn't exist"""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Read schema file and execute
                with open('federal-schema.sql', 'r') as f:
                    schema = f.read()
                
                # Split by semicolon to execute multiple statements
                statements = schema.split(';')
                for statement in statements:
                    if statement.strip():
                        await cur.execute(statement)
                await conn.commit()
                
        logger.info("Database initialized successfully")
        pool.close()
        await pool.wait_closed()
        return True
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        return False

# Add a helper function to standardize document types
def standardize_document_type(doc_type, title=""):
    """Standardize document types to ensure consistency"""
    if not doc_type or doc_type.lower() == "null" or doc_type.lower() == "none" or doc_type.lower() == "unspecified":
        # Try to infer from title
        title = title.lower()
        if "executive order" in title or title.startswith("eo"):
            return "executive_order"
        elif "notice" in title:
            return "notice"
        elif "proposed rule" in title:
            return "proposed_rule"
        elif "rule" in title:
            return "rule"
        elif "presidential" in title:
            return "presidential_document"
        else:
            return "unspecified"
    
    # Standardize known variations
    doc_type = doc_type.lower()
    if doc_type in ["executive_order", "eo", "executive order", "e.o."]:
        return "executive_order"
    elif doc_type in ["notice", "notices"]:
        return "notice"
    elif doc_type in ["proposed_rule", "proposed rule", "proposed rules"]:
        return "proposed_rule"
    elif doc_type in ["rule", "rules", "final rule"]:
        return "rule"
    elif doc_type in ["presidential_document", "presidential document", "presidential documents"]:
        return "presidential_document"
    else:
        return doc_type

async def insert_documents(documents: List[Dict[str, Any]]) -> Dict[str, int]:
    """Insert documents into the database with conflict handling"""
    pool = await get_pool()
    added = 0
    updated = 0
    
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                for doc in documents:
                    # Standardize document type
                    doc["document_type"] = standardize_document_type(
                        doc.get("document_type"), 
                        doc.get("title", "")
                    )
                    
                    # Check if document already exists
                    await cur.execute(
                        "SELECT id FROM documents WHERE document_number = %s", 
                        (doc.get("document_number"),)
                    )
                    existing = await cur.fetchone()
                    
                    if existing:
                        # Update existing document
                        await cur.execute("""
                        UPDATE documents 
                        SET title = %s, publication_date = %s, document_type = %s, 
                            abstract = %s, html_url = %s, pdf_url = %s, type = %s, subtype = %s
                        WHERE document_number = %s
                        """, (
                            doc.get("title"),
                            doc.get("publication_date"),
                            doc.get("document_type"),
                            doc.get("abstract"),
                            doc.get("html_url"),
                            doc.get("pdf_url"),
                            doc.get("type"),
                            doc.get("subtype"),
                            doc.get("document_number")
                        ))
                        updated += 1
                    else:
                        # Insert new document
                        await cur.execute("""
                        INSERT INTO documents 
                        (document_number, title, publication_date, document_type, abstract, html_url, pdf_url, type, subtype)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (
                            doc.get("document_number"),
                            doc.get("title"),
                            doc.get("publication_date"),
                            doc.get("document_type"),
                            doc.get("abstract"),
                            doc.get("html_url"),
                            doc.get("pdf_url"),
                            doc.get("type"),
                            doc.get("subtype")
                        ))
                        added += 1
                
                # Record pipeline run
                if added > 0 or updated > 0:
                    # Determine date range
                    dates = [doc.get("publication_date") for doc in documents if doc.get("publication_date")]
                    if dates:
                        start_date = min(dates)
                        end_date = max(dates)
                        
                        await cur.execute("""
                        INSERT INTO pipeline_runs 
                        (start_date, end_date, documents_added, documents_updated)
                        VALUES (%s, %s, %s, %s)
                        """, (start_date, end_date, added, updated))
                
                await conn.commit()
        
        logger.info(f"Added {added} new documents, updated {updated} documents")
        return {"added": added, "updated": updated}
    
    except Exception as e:
        logger.error(f"Error inserting documents: {str(e)}")
        return {"added": 0, "updated": 0, "error": str(e)}
    
    finally:
        pool.close()
        await pool.wait_closed()

async def query_documents(
    keywords: Optional[str] = None,
    document_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """Query documents from the database based on criteria"""
    pool = await get_pool()
    result = []
    
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Standardize document type if provided
                if document_type:
                    document_type = standardize_document_type(document_type)
                
                # Build query dynamically
                query = "SELECT * FROM documents WHERE 1=1"
                params = []
                
                if keywords:
                    # Use MySQL fulltext search
                    query += " AND MATCH(title, abstract) AGAINST(%s IN NATURAL LANGUAGE MODE)"
                    params.append(keywords)
                
                if document_type:
                    query += " AND document_type = %s"
                    params.append(document_type)
                
                if start_date:
                    query += " AND publication_date >= %s"
                    params.append(start_date)
                
                if end_date:
                    query += " AND publication_date <= %s"
                    params.append(end_date)
                
                query += " ORDER BY publication_date DESC LIMIT %s"
                params.append(limit)
                
                await cur.execute(query, params)
                result = await cur.fetchall()
                
                # Convert datetime objects to strings for JSON serialization and handle nulls
                for doc in result:
                    if "publication_date" in doc and doc["publication_date"]:
                        doc["publication_date"] = doc["publication_date"].isoformat()
                    if "created_at" in doc and doc["created_at"]:
                        doc["created_at"] = doc["created_at"].isoformat()
                    
                    # Handle null document_type and standardize
                    if "document_type" in doc:
                        doc["document_type"] = standardize_document_type(
                            doc.get("document_type"), 
                            doc.get("title", "")
                        )
        
        return result
    
    except Exception as e:
        logger.error(f"Error querying documents: {str(e)}")
        return []
    
    finally:
        pool.close()
        await pool.wait_closed()

async def get_database_stats() -> Dict[str, Any]:
    """Get database statistics for UI"""
    pool = await get_pool()
    stats = {
        "total_documents": 0,
        "document_types": {},
        "date_range": {"min": None, "max": None},
        "last_update": None
    }
    
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Get document count
                await cur.execute("SELECT COUNT(*) as count FROM documents")
                result = await cur.fetchone()
                stats["total_documents"] = result["count"] if result else 0
                
                # First, get a list of all documents with document types
                # This avoids the GROUP BY issue while still allowing us to process titles
                await cur.execute("SELECT id, document_type, title FROM documents")
                documents = await cur.fetchall()
                
                # Process document types through standardization
                doc_type_counts = {}
                for doc in documents:
                    doc_type = standardize_document_type(
                        doc.get("document_type", "unspecified"), 
                        doc.get("title", "")
                    )
                    doc_type_counts[doc_type] = doc_type_counts.get(doc_type, 0) + 1
                
                # Add the document type counts to the stats
                stats["document_types"] = doc_type_counts
                
                # Get date range
                await cur.execute("SELECT MIN(publication_date) as min_date, MAX(publication_date) as max_date FROM documents")
                date_result = await cur.fetchone()
                if date_result:
                    stats["date_range"]["min"] = date_result["min_date"].isoformat() if date_result["min_date"] else None
                    stats["date_range"]["max"] = date_result["max_date"].isoformat() if date_result["max_date"] else None
                
                # Get last update time
                await cur.execute("SELECT MAX(run_date) as last_update FROM pipeline_runs")
                update_result = await cur.fetchone()
                stats["last_update"] = update_result["last_update"].isoformat() if update_result and update_result["last_update"] else None
        
        return stats
    
    except Exception as e:
        logger.error(f"Error getting database stats: {str(e)}")
        return stats
    
    finally:
        pool.close()
        await pool.wait_closed()

async def log_chat(session_id: str, query: str, response: str, tools_used: Optional[List[str]] = None) -> bool:
    """Log chat interaction to database (optional)"""
    pool = await get_pool()
    
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                tools_json = json.dumps(tools_used) if tools_used else None
                
                await cur.execute("""
                INSERT INTO chat_history 
                (session_id, query, response, tools_used)
                VALUES (%s, %s, %s, %s)
                """, (session_id, query, response, tools_json))
                
                await conn.commit()
        return True
    
    except Exception as e:
        logger.error(f"Error logging chat: {str(e)}")
        return False
    
    finally:
        pool.close()
        await pool.wait_closed() 