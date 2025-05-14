#!/usr/bin/env python
import argparse
import subprocess
import sys
import os
import time
import signal
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("run_script")

def run_pipeline():
    """Run the data pipeline to fetch the latest Federal Register data"""
    logger.info("Starting data pipeline...")
    try:
        from pipeline.main import run_pipeline
        import asyncio
        result = asyncio.run(run_pipeline())
        logger.info(f"Pipeline completed successfully: {result}")
        return True
    except Exception as e:
        logger.error(f"Error running pipeline: {str(e)}")
        return False

def start_api_server():
    """Start the FastAPI server"""
    logger.info("Starting API server...")
    try:
        subprocess.Popen([
            sys.executable, 
            "-m", "uvicorn", 
            "api.main:app", 
            "--host", "0.0.0.0",
            "--port", "8000",
            "--reload"
        ])
        logger.info("API server started. Access the interface at http://localhost:8000")
        return True
    except Exception as e:
        logger.error(f"Error starting API server: {str(e)}")
        return False

def check_ollama():
    """Check if Ollama is running"""
    import aiohttp
    import asyncio
    
    async def _check():
        try:
            ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{ollama_url}/api/tags") as response:
                    if response.status == 200:
                        data = await response.json()
                        models = [model["name"] for model in data.get("models", [])]
                        if "qwen2.5:1.5b-instruct-q4_K_M" in models:
                            logger.info("Found Qwen2.5 1B model in Ollama")
                            return True
                        else:
                            logger.warning("Ollama is running but Qwen2.5 1.5B model is not available.")
                            logger.info("Please run 'ollama pull ollama pull qwen2.5:1.5b-instruct-q4_K_M' to download the model.")
                            return False
                    else:
                        logger.warning(f"Ollama returned status code {response.status}")
                        return False
        except Exception as e:
            logger.warning(f"Error checking Ollama: {str(e)}")
            return False
    
    return asyncio.run(_check())

def main():
    parser = argparse.ArgumentParser(description='Federal Register Assistant Runner')
    parser.add_argument('--pipeline', action='store_true', help='Run the data pipeline')
    parser.add_argument('--api', action='store_true', help='Start the API server')
    parser.add_argument('--all', action='store_true', help='Run pipeline and start API server')
    parser.add_argument('--check', action='store_true', help='Check system configuration')
    
    args = parser.parse_args()
    
    if args.check:
        print("Checking system configuration...")
        check_ollama()
        return
    
    if args.all or (not args.pipeline and not args.api):
        # Run both pipeline and API
        if run_pipeline():
            start_api_server()
            
            # Keep the script running
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                logger.info("Stopping services...")
                # Additional cleanup could be added here
    elif args.pipeline:
        # Only run pipeline
        run_pipeline()
    elif args.api:
        # Only start API
        start_api_server()
        
        # Keep the script running
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Stopping API server...")
            # Additional cleanup could be added here

if __name__ == "__main__":
    main() 