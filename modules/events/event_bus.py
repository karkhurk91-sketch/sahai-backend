import redis.asyncio as redis
import json

class EventBus:
    def __init__(self):
        self.redis = redis.from_url("redis://localhost:6379/2", decode_responses=True)
    
    async def publish(self, channel: str, event: dict):
        await self.redis.publish(channel, json.dumps(event))
    
    async def subscribe(self, channel: str, callback):
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(channel)
        async for message in pubsub.listen():
            if message['type'] == 'message':
                await callback(json.loads(message['data']))