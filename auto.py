from modules.queue.producer import celery_app

# This simulates the message that was queued
result = celery_app.send_task(
    'process_incoming_message',
    args=[{
        "from_number": "917290097178",
        "text": "Hi",
        "org_id": "20085b0b-c5bd-4290-aefa-77922dc7f00a"
    }]
)

# Wait up to 10 seconds for the result
try:
    print(result.get(timeout=10))
except Exception as e:
    print(f"Task failed: {e}")