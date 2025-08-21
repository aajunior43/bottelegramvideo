#!/usr/bin/env python3
"""
Gerenciador de Fila Refatorado - Versão 2.1.0

Melhorias implementadas:
- Classe QueueManager centralizada
- Melhor persistência de dados
- Sistema de prioridades aprimorado
- Estatísticas detalhadas
- Backup automático
- Validação de dados
- Thread safety melhorado
- Sistema de eventos
"""

import asyncio
import json
import logging
import os
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any, Union
from uuid import uuid4


class QueueStatus(Enum):
    """Estados possíveis de um item na fila."""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class Priority(Enum):
    """Níveis de prioridade."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    
    def __lt__(self, other):
        priority_order = {Priority.LOW: 0, Priority.NORMAL: 1, Priority.HIGH: 2, Priority.URGENT: 3}
        return priority_order[self] < priority_order[other]


class DownloadType(Enum):
    """Tipos de download suportados."""
    VIDEO = "video"
    AUDIO = "audio"
    IMAGES = "images"
    STORY = "story"
    PLAYLIST = "playlist"
    GENERIC_QUALITY = "generic_quality"
    VIDEO_CUT = "video_cut"


@dataclass
class QueueItemData:
    """Dados de um item da fila usando dataclass para melhor estrutura."""
    id: str
    chat_id: int
    url: str
    download_type: DownloadType
    user_name: str
    priority: Priority
    status: QueueStatus
    created_time: str
    started_time: Optional[str] = None
    completed_time: Optional[str] = None
    error_message: Optional[str] = None
    format_id: Optional[str] = None
    video_index: Optional[int] = None
    progress: float = 0.0
    file_size: Optional[int] = None
    retry_count: int = 0
    max_retries: int = 3
    metadata: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        """Converte strings para enums se necessário."""
        if isinstance(self.download_type, str):
            self.download_type = DownloadType(self.download_type)
        if isinstance(self.priority, str):
            self.priority = Priority(self.priority)
        if isinstance(self.status, str):
            self.status = QueueStatus(self.status)
        if self.metadata is None:
            self.metadata = {}
    
    @property
    def age_seconds(self) -> float:
        """Retorna idade do item em segundos."""
        created = datetime.fromisoformat(self.created_time)
        return (datetime.now() - created).total_seconds()
    
    @property
    def processing_time(self) -> Optional[float]:
        """Retorna tempo de processamento em segundos."""
        if self.started_time and self.completed_time:
            start = datetime.fromisoformat(self.started_time)
            end = datetime.fromisoformat(self.completed_time)
            return (end - start).total_seconds()
        return None
    
    def can_retry(self) -> bool:
        """Verifica se o item pode ser reprocessado."""
        return self.retry_count < self.max_retries and self.status == QueueStatus.FAILED
    
    def to_dict(self) -> Dict[str, Any]:
        """Converte para dicionário para serialização."""
        data = asdict(self)
        # Converte enums para strings
        data['download_type'] = self.download_type.value
        data['priority'] = self.priority.value
        data['status'] = self.status.value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'QueueItemData':
        """Cria instância a partir de dicionário."""
        return cls(**data)


class QueueEventListener(ABC):
    """Interface para listeners de eventos da fila."""
    
    @abstractmethod
    async def on_item_added(self, item: QueueItemData) -> None:
        """Chamado quando item é adicionado."""
        pass
    
    @abstractmethod
    async def on_item_started(self, item: QueueItemData) -> None:
        """Chamado quando item inicia processamento."""
        pass
    
    @abstractmethod
    async def on_item_completed(self, item: QueueItemData) -> None:
        """Chamado quando item é concluído."""
        pass
    
    @abstractmethod
    async def on_item_failed(self, item: QueueItemData) -> None:
        """Chamado quando item falha."""
        pass


@dataclass
class QueueConfig:
    """Configuração do gerenciador de fila."""
    queue_file: str = "download_queue.json"
    backup_file: str = "download_queue_backup.json"
    auto_backup_interval: int = 300  # 5 minutos
    max_queue_size: int = 1000
    max_completed_items: int = 100
    auto_cleanup_age: int = 86400  # 24 horas
    enable_persistence: bool = True
    enable_auto_backup: bool = True
    
    def __post_init__(self):
        """Cria diretórios necessários."""
        for file_path in [self.queue_file, self.backup_file]:
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)


class QueueStatistics:
    """Estatísticas detalhadas da fila."""
    
    def __init__(self, items: List[QueueItemData]):
        self.items = items
        self._calculate_stats()
    
    def _calculate_stats(self):
        """Calcula estatísticas."""
        self.total = len(self.items)
        
        # Por status
        self.by_status = {}
        for status in QueueStatus:
            self.by_status[status] = len([i for i in self.items if i.status == status])
        
        # Por prioridade
        self.by_priority = {}
        for priority in Priority:
            self.by_priority[priority] = len([i for i in self.items if i.priority == priority])
        
        # Por tipo de download
        self.by_type = {}
        for download_type in DownloadType:
            self.by_type[download_type] = len([i for i in self.items if i.download_type == download_type])
        
        # Tempos de processamento
        processing_times = [i.processing_time for i in self.items if i.processing_time is not None]
        if processing_times:
            self.avg_processing_time = sum(processing_times) / len(processing_times)
            self.min_processing_time = min(processing_times)
            self.max_processing_time = max(processing_times)
        else:
            self.avg_processing_time = 0
            self.min_processing_time = 0
            self.max_processing_time = 0
        
        # Taxa de sucesso
        completed = self.by_status.get(QueueStatus.COMPLETED, 0)
        failed = self.by_status.get(QueueStatus.FAILED, 0)
        total_processed = completed + failed
        self.success_rate = (completed / total_processed * 100) if total_processed > 0 else 0
    
    def get_user_stats(self, chat_id: int) -> Dict[str, Any]:
        """Retorna estatísticas específicas do usuário."""
        user_items = [i for i in self.items if i.chat_id == chat_id]
        
        if not user_items:
            return {
                'total': 0,
                'pending': 0,
                'downloading': 0,
                'completed': 0,
                'failed': 0,
                'success_rate': 0
            }
        
        user_stats = QueueStatistics(user_items)
        return {
            'total': user_stats.total,
            'pending': user_stats.by_status.get(QueueStatus.PENDING, 0),
            'downloading': user_stats.by_status.get(QueueStatus.DOWNLOADING, 0),
            'processing': user_stats.by_status.get(QueueStatus.PROCESSING, 0),
            'completed': user_stats.by_status.get(QueueStatus.COMPLETED, 0),
            'failed': user_stats.by_status.get(QueueStatus.FAILED, 0),
            'cancelled': user_stats.by_status.get(QueueStatus.CANCELLED, 0),
            'success_rate': user_stats.success_rate,
            'avg_processing_time': user_stats.avg_processing_time
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Converte estatísticas para dicionário."""
        return {
            'total': self.total,
            'by_status': {k.value: v for k, v in self.by_status.items()},
            'by_priority': {k.value: v for k, v in self.by_priority.items()},
            'by_type': {k.value: v for k, v in self.by_type.items()},
            'avg_processing_time': self.avg_processing_time,
            'min_processing_time': self.min_processing_time,
            'max_processing_time': self.max_processing_time,
            'success_rate': self.success_rate
        }


class QueueManager:
    """Gerenciador principal da fila de downloads."""
    
    def __init__(self, config: Optional[QueueConfig] = None):
        self.config = config or QueueConfig()
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Estado interno
        self._queue: List[QueueItemData] = []
        self._lock = asyncio.Lock()
        self._current_download: Optional[QueueItemData] = None
        self._listeners: List[QueueEventListener] = []
        self._backup_task: Optional[asyncio.Task] = None
        
        # Carrega fila existente
        if self.config.enable_persistence:
            self._load_queue()
        
        # Inicia backup automático
        if self.config.enable_auto_backup:
            self._start_auto_backup()
    
    async def add_item(
        self,
        chat_id: int,
        url: str,
        download_type: Union[DownloadType, str],
        user_name: str = "Usuário",
        priority: Union[Priority, str] = Priority.NORMAL,
        **kwargs
    ) -> QueueItemData:
        """Adiciona item à fila."""
        async with self._lock:
            # Verifica limite da fila
            if len(self._queue) >= self.config.max_queue_size:
                raise ValueError(f"Fila atingiu limite máximo de {self.config.max_queue_size} itens")
            
            # Converte strings para enums
            if isinstance(download_type, str):
                download_type = DownloadType(download_type)
            if isinstance(priority, str):
                priority = Priority(priority)
            
            # Cria item
            item = QueueItemData(
                id=str(uuid4()),
                chat_id=chat_id,
                url=url,
                download_type=download_type,
                user_name=user_name,
                priority=priority,
                status=QueueStatus.PENDING,
                created_time=datetime.now().isoformat(),
                **kwargs
            )
            
            # Adiciona na posição correta baseado na prioridade
            self._insert_by_priority(item)
            
            # Salva e notifica
            self._save_queue()
            await self._notify_listeners('on_item_added', item)
            
            self.logger.info(f"Item adicionado à fila: {item.id} - {download_type.value} - {url[:50]}...")
            return item
    
    def _insert_by_priority(self, item: QueueItemData) -> None:
        """Insere item na posição correta baseado na prioridade."""
        # Encontra posição correta
        insert_pos = len(self._queue)
        for i, existing_item in enumerate(self._queue):
            if (existing_item.status == QueueStatus.PENDING and 
                item.priority.value > existing_item.priority.value):
                insert_pos = i
                break
        
        self._queue.insert(insert_pos, item)
    
    async def get_next_item(self) -> Optional[QueueItemData]:
        """Obtém próximo item para processamento."""
        async with self._lock:
            for item in self._queue:
                if item.status == QueueStatus.PENDING:
                    item.status = QueueStatus.DOWNLOADING
                    item.started_time = datetime.now().isoformat()
                    self._current_download = item
                    self._save_queue()
                    await self._notify_listeners('on_item_started', item)
                    return item
            return None
    
    async def update_item_status(
        self,
        item_id: str,
        status: Union[QueueStatus, str],
        error_message: Optional[str] = None,
        progress: Optional[float] = None
    ) -> bool:
        """Atualiza status de um item."""
        async with self._lock:
            item = self._find_item(item_id)
            if not item:
                return False
            
            if isinstance(status, str):
                status = QueueStatus(status)
            
            old_status = item.status
            item.status = status
            
            if error_message:
                item.error_message = error_message
            
            if progress is not None:
                item.progress = max(0, min(100, progress))
            
            if status in [QueueStatus.COMPLETED, QueueStatus.FAILED, QueueStatus.CANCELLED]:
                item.completed_time = datetime.now().isoformat()
                if self._current_download and self._current_download.id == item_id:
                    self._current_download = None
            
            self._save_queue()
            
            # Notifica listeners
            if status == QueueStatus.COMPLETED:
                await self._notify_listeners('on_item_completed', item)
            elif status == QueueStatus.FAILED:
                await self._notify_listeners('on_item_failed', item)
            
            return True
    
    async def retry_item(self, item_id: str) -> bool:
        """Tenta reprocessar um item falhado."""
        async with self._lock:
            item = self._find_item(item_id)
            if not item or not item.can_retry():
                return False
            
            item.status = QueueStatus.PENDING
            item.retry_count += 1
            item.error_message = None
            item.progress = 0.0
            item.started_time = None
            item.completed_time = None
            
            # Reinsere na fila com prioridade
            self._queue.remove(item)
            self._insert_by_priority(item)
            
            self._save_queue()
            self.logger.info(f"Item {item_id} marcado para retry ({item.retry_count}/{item.max_retries})")
            return True
    
    async def remove_item(self, item_id: str) -> bool:
        """Remove item da fila."""
        async with self._lock:
            item = self._find_item(item_id)
            if not item:
                return False
            
            self._queue.remove(item)
            
            if self._current_download and self._current_download.id == item_id:
                self._current_download = None
            
            self._save_queue()
            self.logger.info(f"Item removido da fila: {item_id}")
            return True
    
    async def clear_user_queue(self, chat_id: int) -> int:
        """Remove todos os itens de um usuário."""
        async with self._lock:
            user_items = [item for item in self._queue if item.chat_id == chat_id]
            count = len(user_items)
            
            self._queue = [item for item in self._queue if item.chat_id != chat_id]
            
            # Limpa download atual se for do usuário
            if (self._current_download and 
                self._current_download.chat_id == chat_id):
                self._current_download = None
            
            self._save_queue()
            self.logger.info(f"Fila do usuário {chat_id} limpa: {count} itens removidos")
            return count
    
    async def clear_completed_items(self, chat_id: Optional[int] = None) -> int:
        """Remove itens concluídos."""
        async with self._lock:
            if chat_id:
                completed_items = [
                    item for item in self._queue 
                    if item.chat_id == chat_id and item.status == QueueStatus.COMPLETED
                ]
                self._queue = [
                    item for item in self._queue 
                    if not (item.chat_id == chat_id and item.status == QueueStatus.COMPLETED)
                ]
            else:
                completed_items = [item for item in self._queue if item.status == QueueStatus.COMPLETED]
                self._queue = [item for item in self._queue if item.status != QueueStatus.COMPLETED]
            
            count = len(completed_items)
            self._save_queue()
            self.logger.info(f"Itens concluídos removidos: {count}")
            return count
    
    async def cleanup_old_items(self) -> int:
        """Remove itens antigos automaticamente."""
        async with self._lock:
            cutoff_time = datetime.now() - timedelta(seconds=self.config.auto_cleanup_age)
            
            old_items = [
                item for item in self._queue
                if (item.status in [QueueStatus.COMPLETED, QueueStatus.FAILED] and
                    datetime.fromisoformat(item.created_time) < cutoff_time)
            ]
            
            for item in old_items:
                self._queue.remove(item)
            
            count = len(old_items)
            if count > 0:
                self._save_queue()
                self.logger.info(f"Limpeza automática: {count} itens antigos removidos")
            
            return count
    
    def get_statistics(self, chat_id: Optional[int] = None) -> Union[QueueStatistics, Dict[str, Any]]:
        """Retorna estatísticas da fila."""
        if chat_id:
            stats = QueueStatistics(self._queue)
            return stats.get_user_stats(chat_id)
        else:
            return QueueStatistics(self._queue)
    
    def get_user_items(self, chat_id: int) -> List[QueueItemData]:
        """Retorna itens de um usuário específico."""
        return [item for item in self._queue if item.chat_id == chat_id]
    
    def get_current_download(self) -> Optional[QueueItemData]:
        """Retorna item atualmente sendo processado."""
        return self._current_download
    
    def is_processing(self) -> bool:
        """Verifica se há processamento ativo."""
        return self._current_download is not None
    
    def get_queue_position(self, item_id: str) -> int:
        """Retorna posição do item na fila (apenas pendentes)."""
        pending_items = [item for item in self._queue if item.status == QueueStatus.PENDING]
        for i, item in enumerate(pending_items):
            if item.id == item_id:
                return i + 1
        return -1
    
    def add_listener(self, listener: QueueEventListener) -> None:
        """Adiciona listener de eventos."""
        self._listeners.append(listener)
    
    def remove_listener(self, listener: QueueEventListener) -> None:
        """Remove listener de eventos."""
        if listener in self._listeners:
            self._listeners.remove(listener)
    
    async def _notify_listeners(self, method_name: str, item: QueueItemData) -> None:
        """Notifica todos os listeners."""
        for listener in self._listeners:
            try:
                method = getattr(listener, method_name)
                await method(item)
            except Exception as e:
                self.logger.error(f"Erro ao notificar listener: {e}")
    
    def _find_item(self, item_id: str) -> Optional[QueueItemData]:
        """Encontra item por ID."""
        for item in self._queue:
            if item.id == item_id:
                return item
        return None
    
    def _load_queue(self) -> None:
        """Carrega fila do arquivo."""
        try:
            if os.path.exists(self.config.queue_file):
                with open(self.config.queue_file, 'r', encoding='utf-8') as f:
                    queue_data = json.load(f)
                    self._queue = [QueueItemData.from_dict(item) for item in queue_data]
                
                # Reseta itens que estavam sendo processados
                for item in self._queue:
                    if item.status == QueueStatus.DOWNLOADING:
                        item.status = QueueStatus.PENDING
                        item.started_time = None
                
                self.logger.info(f"Fila carregada com {len(self._queue)} itens")
            else:
                self._queue = []
        except Exception as e:
            self.logger.error(f"Erro ao carregar fila: {e}")
            # Tenta carregar backup
            self._load_backup()
    
    def _load_backup(self) -> None:
        """Carrega fila do backup."""
        try:
            if os.path.exists(self.config.backup_file):
                with open(self.config.backup_file, 'r', encoding='utf-8') as f:
                    queue_data = json.load(f)
                    self._queue = [QueueItemData.from_dict(item) for item in queue_data]
                self.logger.info(f"Fila carregada do backup com {len(self._queue)} itens")
            else:
                self._queue = []
        except Exception as e:
            self.logger.error(f"Erro ao carregar backup: {e}")
            self._queue = []
    
    def _save_queue(self) -> None:
        """Salva fila no arquivo."""
        if not self.config.enable_persistence:
            return
        
        try:
            queue_data = [item.to_dict() for item in self._queue]
            
            # Salva arquivo principal
            with open(self.config.queue_file, 'w', encoding='utf-8') as f:
                json.dump(queue_data, f, indent=2, ensure_ascii=False)
            
            # Mantém apenas itens recentes para evitar arquivo muito grande
            if len(self._queue) > self.config.max_completed_items:
                # Remove itens concluídos mais antigos
                completed_items = [
                    item for item in self._queue 
                    if item.status in [QueueStatus.COMPLETED, QueueStatus.FAILED]
                ]
                if len(completed_items) > self.config.max_completed_items:
                    completed_items.sort(key=lambda x: x.completed_time or x.created_time)
                    items_to_remove = completed_items[:-self.config.max_completed_items]
                    for item in items_to_remove:
                        self._queue.remove(item)
        
        except Exception as e:
            self.logger.error(f"Erro ao salvar fila: {e}")
    
    def _start_auto_backup(self) -> None:
        """Inicia backup automático."""
        async def backup_loop():
            while True:
                try:
                    await asyncio.sleep(self.config.auto_backup_interval)
                    self._create_backup()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self.logger.error(f"Erro no backup automático: {e}")
        
        self._backup_task = asyncio.create_task(backup_loop())
    
    def _create_backup(self) -> None:
        """Cria backup da fila."""
        try:
            if os.path.exists(self.config.queue_file):
                shutil.copy2(self.config.queue_file, self.config.backup_file)
                self.logger.debug("Backup da fila criado")
        except Exception as e:
            self.logger.error(f"Erro ao criar backup: {e}")
    
    async def shutdown(self) -> None:
        """Finaliza o gerenciador."""
        if self._backup_task:
            self._backup_task.cancel()
            try:
                await self._backup_task
            except asyncio.CancelledError:
                pass
        
        self._create_backup()
        self.logger.info("QueueManager finalizado")


# Instância global para compatibilidade
_queue_manager = QueueManager()

# Variáveis globais para compatibilidade
download_queue = _queue_manager._queue
queue_lock = _queue_manager._lock
current_download = _queue_manager._current_download

# Funções de compatibilidade
async def add_to_queue(chat_id, url, download_type, user_name="Usuário", priority="normal", format_id=None, video_index=None):
    """Função de compatibilidade."""
    return await _queue_manager.add_item(
        chat_id=chat_id,
        url=url,
        download_type=download_type,
        user_name=user_name,
        priority=priority,
        format_id=format_id,
        video_index=video_index
    )

async def get_next_queue_item():
    """Função de compatibilidade."""
    return await _queue_manager.get_next_item()

def is_queue_processing():
    """Função de compatibilidade."""
    return _queue_manager.is_processing()

async def clear_user_queue(chat_id):
    """Função de compatibilidade."""
    return await _queue_manager.clear_user_queue(chat_id)

async def clear_completed_items(chat_id):
    """Função de compatibilidade."""
    return await _queue_manager.clear_completed_items(chat_id)

def get_user_queue_stats(chat_id):
    """Função de compatibilidade."""
    stats = _queue_manager.get_statistics(chat_id)
    user_items = _queue_manager.get_user_items(chat_id)
    return stats, user_items

def save_queue():
    """Função de compatibilidade."""
    _queue_manager._save_queue()

def load_queue():
    """Função de compatibilidade."""
    _queue_manager._load_queue()

# Classe QueueItem para compatibilidade
class QueueItem:
    """Classe de compatibilidade."""
    def __init__(self, chat_id, url, download_type, user_name="Usuário", priority="normal"):
        self.data = QueueItemData(
            id=str(uuid4()),
            chat_id=chat_id,
            url=url,
            download_type=DownloadType(download_type),
            user_name=user_name,
            priority=Priority(priority),
            status=QueueStatus.PENDING,
            created_time=datetime.now().isoformat()
        )
    
    def __getattr__(self, name):
        return getattr(self.data, name)
    
    def to_dict(self):
        return self.data.to_dict()
    
    @classmethod
    def from_dict(cls, data):
        item = cls(data['chat_id'], data['url'], data['download_type'])
        item.data = QueueItemData.from_dict(data)
        return item