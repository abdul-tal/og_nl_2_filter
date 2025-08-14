"""Conversation memory store for maintaining chat history by conversation_id."""

import threading
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from ..models.filter_models import ConversationMessage

class ConversationStore:
    """Thread-safe conversation memory store."""
    
    def __init__(self, max_messages_per_conversation: int = 50, cleanup_after_hours: int = 24):
        self._conversations: Dict[str, List[ConversationMessage]] = {}
        self._last_activity: Dict[str, datetime] = {}
        self._lock = threading.Lock()
        self.max_messages = max_messages_per_conversation
        self.cleanup_after = timedelta(hours=cleanup_after_hours)
    
    def add_message(self, conversation_id: str, role: str, content: str) -> None:
        """Add a message to the conversation history."""
        with self._lock:
            if conversation_id not in self._conversations:
                self._conversations[conversation_id] = []
            
            message = ConversationMessage(
                role=role,
                content=content,
                timestamp=datetime.now().isoformat()
            )
            
            self._conversations[conversation_id].append(message)
            self._last_activity[conversation_id] = datetime.now()
            
            # Keep only the last N messages to prevent memory bloat
            if len(self._conversations[conversation_id]) > self.max_messages:
                self._conversations[conversation_id] = self._conversations[conversation_id][-self.max_messages:]
    
    def get_conversation_history(self, conversation_id: str, last_n_messages: int = 10) -> List[ConversationMessage]:
        """Get conversation history for a given conversation_id."""
        with self._lock:
            if conversation_id not in self._conversations:
                return []
            
            messages = self._conversations[conversation_id]
            return messages[-last_n_messages:] if last_n_messages else messages
    
    def get_last_assistant_message(self, conversation_id: str) -> Optional[ConversationMessage]:
        """Get the last assistant message for context detection."""
        with self._lock:
            if conversation_id not in self._conversations:
                return None
            
            # Find the last assistant message
            for message in reversed(self._conversations[conversation_id]):
                if message.role == "assistant":
                    return message
            return None
    
    def clear_conversation(self, conversation_id: str) -> None:
        """Clear conversation history for a specific conversation_id."""
        with self._lock:
            if conversation_id in self._conversations:
                del self._conversations[conversation_id]
            if conversation_id in self._last_activity:
                del self._last_activity[conversation_id]
    
    def cleanup_old_conversations(self) -> int:
        """Clean up conversations that haven't been active for a while."""
        cutoff_time = datetime.now() - self.cleanup_after
        cleaned_count = 0
        
        with self._lock:
            expired_conversations = [
                conv_id for conv_id, last_activity 
                in self._last_activity.items() 
                if last_activity < cutoff_time
            ]
            
            for conv_id in expired_conversations:
                if conv_id in self._conversations:
                    del self._conversations[conv_id]
                del self._last_activity[conv_id]
                cleaned_count += 1
        
        return cleaned_count
    
    def get_stats(self) -> Dict[str, int]:
        """Get store statistics."""
        with self._lock:
            return {
                "total_conversations": len(self._conversations),
                "total_messages": sum(len(messages) for messages in self._conversations.values())
            }


# Global conversation store instance
conversation_store = ConversationStore()
