import json
import asyncio
import aiofiles
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("processor")

async def process_federal_register_data(data: Dict[str, Any], date: datetime) -> List[Dict[str, Any]]:
    """Process downloaded Federal Register data into a consistent format"""
    processed_documents = []
    
    # Create processed directory if not exists
    processed_dir = f"data/processed/{date.strftime('%Y%m%d')}"
    os.makedirs(processed_dir, exist_ok=True)
    
    try:
        # Extract documents from API response
        documents = data.get("results", [])
        
        for doc in documents:
            processed_doc = {
                "document_number": doc.get("document_number"),
                "title": doc.get("title"),
                "publication_date": doc.get("publication_date"),
                "document_type": doc.get("document_type"),
                "abstract": doc.get("abstract", ""),
                "html_url": doc.get("html_url"),
                "pdf_url": doc.get("pdf_url"),
                "type": doc.get("type"),
                "subtype": doc.get("subtype")
            }
            
            # Clean and validate fields
            if not processed_doc["document_number"]:
                continue  # Skip documents without a document number
                
            if not processed_doc["title"]:
                processed_doc["title"] = "Untitled Document"
                
            # Ensure publication date is in YYYY-MM-DD format
            if isinstance(processed_doc["publication_date"], str):
                try:
                    # Validate and normalize date format
                    parsed_date = datetime.strptime(processed_doc["publication_date"], "%Y-%m-%d")
                    processed_doc["publication_date"] = parsed_date.strftime("%Y-%m-%d")
                except ValueError:
                    # If invalid date, use the provided date
                    processed_doc["publication_date"] = date.strftime("%Y-%m-%d")
            else:
                processed_doc["publication_date"] = date.strftime("%Y-%m-%d")
            
            processed_documents.append(processed_doc)
        
        # Save processed data
        async with aiofiles.open(f"{processed_dir}/processed_documents.json", "w") as f:
            await f.write(json.dumps(processed_documents, indent=2))
        
        logger.info(f"Processed {len(processed_documents)} documents for {date.strftime('%Y-%m-%d')}")
        return processed_documents
        
    except Exception as e:
        logger.error(f"Error processing data for {date.strftime('%Y-%m-%d')}: {str(e)}")
        return []

async def enrich_documents(documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Enrich documents with additional metadata (optional enhancement)
    
    This function could be expanded to:
    1. Extract keywords from abstracts
    2. Add sentiment analysis
    3. Link related documents
    4. Add readability scores
    """
    # For now, just return the original documents
    # This is a placeholder for future enhancements
    return documents

async def generate_document_summary(abstract: str) -> str:
    """Generate a shorter summary of document abstracts (optional)
    
    This could be implemented with an LLM for abstractive summarization,
    but would increase complexity and resource usage.
    """
    # Simple extractive summarization - just return the first 2 sentences
    if not abstract:
        return ""
    
    sentences = abstract.split('. ')
    summary = '. '.join(sentences[:min(2, len(sentences))])
    
    # Add period if missing
    if summary and not summary.endswith('.'):
        summary += '.'
        
    return summary 