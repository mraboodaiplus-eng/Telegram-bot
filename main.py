# Alpha Predator Bot - Main File
import time
import os

print("Bot starting up...")
print("Heartbeat service initiated. The bot is alive.")

# This loop keeps the script running for Render's free tier.
while True:
    print(f"Heartbeat: {time.ctime()}")
    time.sleep(600) # Print a message every 10 minutes
