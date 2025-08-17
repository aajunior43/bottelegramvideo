import asyncio
import json
import logging
import os
from datetime import datetime
from typing import List, Optional

# Configura o logger
logger = logging.getLogger(__name__)

# Variáveis globais para a fila
download_queue = []  # Lista global para fila de downloads
queue_lock = asyncio.Lock()  # Lock para operações thread-safe
current_download = None  # Download atual em processamento
queue_file = 'download_queue.json'  # Arquivo para persistir a fila

class QueueItem:
    def __init__(self, chat_id, url, download_type, user_name="Usuário", priority="normal"):
        self.id = f"{chat_id}_{int(datetime.now().timestamp())}"
        self.chat_id = chat_id
        self.url = url
        self.download_type = download_type  # 'video', 'images', 'audio'
        self.user_name = user_name
        self.priority = priority  # 'high', 'normal', 'low'
        self.status = 'pending'  # 'pending', 'downloading', 'completed', 'failed'
        self.created_time = datetime.now().isoformat()
        self.started_time = None
        self.completed_time = None
        self.error_message = None
        self.format_id = None  # Para downloads com qualidade específica
        self.video_index = None  # Para downloads de vídeo específico da playlist
    
    def to_dict(self):
        return {
            'id': self.id,
            'chat_id': self.chat_id,
            'url': self.url,
            'download_type': self.download_type,
            'user_name': self.user_name,
            'priority': self.priority,
            'status': self.status,
            'created_time': self.created_time,
            'started_time': self.started_time,
            'completed_time': self.completed_time,
            'error_message': self.error_message,
            'format_id': self.format_id,
            'video_index': self.video_index
        }
    
    @classmethod
    def from_dict(cls, data):
        item = cls(data['chat_id'], data['url'], data['download_type'], data['user_name'], data['priority'])
        item.id = data['id']
        item.status = data['status']
        item.created_time = data['created_time']
        item.started_time = data['started_time']
        item.completed_time = data['completed_time']
        item.error_message = data['error_message']
        item.format_id = data.get('format_id')
        item.video_index = data.get('video_index')
        return item

def load_queue():
    """Carrega a fila de downloads do arquivo."""
    global download_queue
    try:
        if os.path.exists(queue_file):
            with open(queue_file, 'r', encoding='utf-8') as f:
                queue_data = json.load(f)
                download_queue = [QueueItem.from_dict(item) for item in queue_data]
            logger.info(f"Fila carregada com {len(download_queue)} itens")
        else:
            download_queue = []
    except Exception as e:
        logger.error(f"Erro ao carregar fila: {e}")
        download_queue = []

def save_queue():
    """Salva a fila de downloads no arquivo."""
    try:
        with open(queue_file, 'w', encoding='utf-8') as f:
            queue_data = [item.to_dict() for item in download_queue]
            json.dump(queue_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Erro ao salvar fila: {e}")

async def add_to_queue(chat_id, url, download_type, user_name="Usuário", priority="normal", format_id=None, video_index=None):
    """Adiciona um item à fila de downloads."""
    async with queue_lock:
        item = QueueItem(chat_id, url, download_type, user_name, priority)
        item.format_id = format_id
        item.video_index = video_index
        
        # Adiciona no início se for alta prioridade
        if priority == "high":
            download_queue.insert(0, item)
        else:
            download_queue.append(item)
        
        save_queue()
        logger.info(f"Item adicionado à fila: {item.id} - {download_type} - {url[:50]}...")
        return item

async def remove_from_queue(item_id):
    """Remove um item da fila."""
    async with queue_lock:
        global download_queue
        download_queue = [item for item in download_queue if item.id != item_id]
        save_queue()

async def get_next_queue_item():
    """Obtém o próximo item da fila para processamento."""
    async with queue_lock:
        for item in download_queue:
            if item.status == 'pending':
                return item
        return None

def is_queue_processing():
    """Verifica se a fila está sendo processada."""
    return current_download is not None

async def clear_user_queue(chat_id):
    """Limpa a fila de downloads de um usuário específico."""
    async with queue_lock:
        global download_queue
        user_items_count = len([item for item in download_queue if item.chat_id == chat_id])
        download_queue = [item for item in download_queue if item.chat_id != chat_id]
        save_queue()
        return user_items_count

async def clear_completed_items(chat_id):
    """Remove itens concluídos da fila de um usuário."""
    async with queue_lock:
        global download_queue
        completed_count = len([item for item in download_queue if item.chat_id == chat_id and item.status == 'completed'])
        download_queue = [item for item in download_queue if not (item.chat_id == chat_id and item.status == 'completed')]
        save_queue()
        return completed_count

def get_user_queue_stats(chat_id):
    """Retorna estatísticas da fila de um usuário."""
    user_items = [item for item in download_queue if item.chat_id == chat_id]
    
    stats = {
        'total': len(user_items),
        'pending': len([i for i in user_items if i.status == 'pending']),
        'downloading': len([i for i in user_items if i.status == 'downloading']),
        'completed': len([i for i in user_items if i.status == 'completed']),
        'failed': len([i for i in user_items if i.status == 'failed'])
    }
    
    return stats, user_items

def get_queue_position(item_id):
    """Retorna a posição de um item na fila."""
    pending_items = [item for item in download_queue if item.status == 'pending']
    for i, item in enumerate(pending_items):
        if item.id == item_id:
            return i + 1
    return -1

# Inicializa a fila ao importar o módulo
load_queue()