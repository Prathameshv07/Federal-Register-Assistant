import asyncio
import aiohttp
import aiofiles
import json
import os
import sys
import logging
from datetime import datetime, timedelta, date
from typing import List, Dict, Any, Optional

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.processor import process_federal_register_data, enrich_documents
from db_connector import init_db, insert_documents

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("pipeline")

# Create a checkpoints directory
os.makedirs("data/checkpoints", exist_ok=True)
CHECKPOINT_FILE = "data/checkpoints/last_processed_date.txt"

async def download_federal_register_data(date: datetime) -> Optional[Dict[str, Any]]:
    """Download data from Federal Register API for specific date"""
    # Format: YYYY-MM-DD
    date_str = date.strftime('%Y-%m-%d')
    
    # Correct API URL according to documentation
    url = (
        f"https://www.federalregister.gov/api/v1/documents.json"
        f"?fields[]=document_number"
        f"&fields[]=title"
        f"&fields[]=publication_date"
        f"&fields[]=type"
#        f"&fields[]=document_type"
        f"&fields[]=abstract"
        f"&fields[]=html_url"
        f"&fields[]=pdf_url"
        f"&fields[]=subtype"
        f"&conditions[publication_date][is]={date_str}"
        f"&per_page=100"
    )

    # Create raw data directory
    raw_dir = f"data/raw/{date.strftime('%Y%m%d')}"
    os.makedirs(raw_dir, exist_ok=True)
    
    try:
        async with aiohttp.ClientSession() as session:
            # Add rate limiting to avoid API throttling
            await asyncio.sleep(1)  # Simple rate limiting
            
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Save raw data
                    async with aiofiles.open(f"{raw_dir}/federal_register.json", "w") as f:
                        await f.write(json.dumps(data, indent=2))
                    
                    logger.info(f"Successfully downloaded data for {date_str}")
                    return data
                else:
                    error_text = await response.text()
                    logger.error(f"Error downloading data for {date_str}: HTTP {response.status} - {error_text}")
                    return None
    except Exception as e:
        logger.error(f"Exception downloading data for {date_str}: {str(e)}")
        return None

async def save_checkpoint(date: datetime) -> None:
    """Save checkpoint of last processed date"""
    async with aiofiles.open(CHECKPOINT_FILE, "w") as f:
        await f.write(date.strftime("%Y-%m-%d"))
    logger.info(f"Updated checkpoint to {date.strftime('%Y-%m-%d')}")

async def load_checkpoint() -> Optional[datetime]:
    """Load last processed date from checkpoint"""
    try:
        if os.path.exists(CHECKPOINT_FILE):
            async with aiofiles.open(CHECKPOINT_FILE, "r") as f:
                date_str = await f.read()
                date_str = date_str.strip()
                return datetime.strptime(date_str, "%Y-%m-%d")
    except Exception as e:
        logger.error(f"Error loading checkpoint: {str(e)}")
    
    # Default to 7 days ago if no checkpoint
    return datetime.now() - timedelta(days=7)

async def run_pipeline(days_back: int = 7) -> Dict[str, Any]:
    """Run complete pipeline for the last N days"""
    # Initialize database
    await init_db()

    # Fix the date order - start date must be before end date
    # datetime(2023, 1, 1) ~ year month date
    # start_date = datetime(2023, 1, 1)
    # end_date = datetime(2023, 5, 1)
    start_date = datetime.now() - timedelta(days=30)
    end_date = datetime.now()

    # Check for checkpoint
    checkpoint_date = await load_checkpoint()
    if checkpoint_date and checkpoint_date > start_date and checkpoint_date < end_date:
        start_date = checkpoint_date

    # Ensure start_date <= end_date
    if start_date > end_date:
        logger.error("Start date is after end date. Adjusting to default range.")
        start_date = end_date - timedelta(days=7)
    
    logger.info(f"Running pipeline from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    
    # Process each day
    current_date = start_date
    results = {
        "days_processed": 0,
        "documents_added": 0,
        "documents_updated": 0,
        "errors": 0
    }
    
    while current_date <= end_date:
        # Download data for the day
        data = await download_federal_register_data(current_date)
        
        if data:
            # Process the data
            processed_data = await process_federal_register_data(data, current_date)
            
            # Enrich documents (optional enhancement)
            enriched_data = await enrich_documents(processed_data)
            
            # Insert into database
            if enriched_data:
                db_result = await insert_documents(enriched_data)
                results["documents_added"] += db_result.get("added", 0)
                results["documents_updated"] += db_result.get("updated", 0)
                if "error" in db_result:
                    results["errors"] += 1
            
            results["days_processed"] += 1
        
        # Save checkpoint after each day
        await save_checkpoint(current_date)
        
        # Move to next day
        current_date += timedelta(days=1)
    
    logger.info(f"Pipeline completed: {results}")
    return results

async def run_single_day(date_str: Optional[str] = None) -> Dict[str, Any]:
    """Run pipeline for a single day (useful for testing)"""
    # Initialize database
    await init_db()
    
    # Parse date or use today
    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            logger.error(f"Invalid date format: {date_str}. Use YYYY-MM-DD.")
            return {"error": "Invalid date format"}
    else:
        target_date = datetime.now()
    
    logger.info(f"Running pipeline for {target_date.strftime('%Y-%m-%d')}")
    
    # Download data
    data = await download_federal_register_data(target_date)
    
    if not data:
        return {"error": "Failed to download data"}
    
    # Process the data
    processed_data = await process_federal_register_data(data, target_date)
    
    # Enrich documents (optional)
    enriched_data = await enrich_documents(processed_data)
    
    # Insert into database
    result = await insert_documents(enriched_data)
    
    # Save checkpoint
    await save_checkpoint(target_date)
    
    logger.info(f"Single day pipeline completed: {result}")
    return result

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Federal Register Data Pipeline')
    parser.add_argument('--days', type=int, default=7, help='Number of days to process (default: 7)')
    parser.add_argument('--date', type=str, help='Single date to process (format: YYYY-MM-DD)')
    
    args = parser.parse_args()
    
    if args.date:
        asyncio.run(run_single_day(args.date))
    else:
        asyncio.run(run_pipeline(args.days)) 