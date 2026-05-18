from langchain_community.chat_message_histories import RedisChatMessageHistory
from langchain.memory import ConversationBufferMemory
from modules.common.config import REDIS_URL

def get_user_memory(user_id: str):
    history = RedisChatMessageHistory(
        session_id=user_id,
        url=REDIS_URL,
        ttl=86400
    )
    return ConversationBufferMemory(
        chat_memory=history,
        return_messages=True,
        memory_key="history"
    )
