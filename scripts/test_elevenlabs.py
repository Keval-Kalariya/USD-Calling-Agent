import asyncio
import os
import sys

# Ensure the root directory is in the path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.streaming.elevenlabs_stream import ElevenLabsStreamClient

async def main():
    print("Initializing ElevenLabsStreamClient...")
    client = ElevenLabsStreamClient()
    print("Testing generate_stream()...")
    
    try:
        async for chunk in client.generate_stream("Testing the text to speech pipeline."):
            print(f"Received chunk of size: {len(chunk)} bytes")
            break # Just need to verify the connection works
            
    except Exception as e:
        print(f"Error occurred: {e}")

if __name__ == "__main__":
    asyncio.run(main())
