from pyrogram import Client, filters
from plugins.file_rename import processing_stats, user_queues, MAX_CONCURRENT_PER_USER

@Client.on_message(filters.private & filters.command("queue"))
async def show_queue_status(client, message):
    # [Queue status function]

@Client.on_message(filters.private & filters.command("clearqueue"))
async def clear_queue(client, message):
    # [Clear queue function]
