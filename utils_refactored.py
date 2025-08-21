#!/usr/bin/env python3
"""
Utilidades Refatoradas - Versão 2.1.0

Melhorias implementadas:
- Classes especializadas para diferentes tipos de utilidades
- Cache para operações custosas
- Validação de entrada mais robusta
- Configuração centralizada
- Melhor tratamento de erros
- Logging estruturado
"""

import asyncio
import glob
import logging
import os
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from PIL import Image


@dataclass
class UtilsConfig:
    """Configuração centralizada para utilitários."""
    temp_file_max_age: int = 3600  # 1 hora em segundos
    progress_bar_length: int = 10
    image_min_resolution: Tuple[int, int] = (200, 200)
    image_min_file_size: int = 10240  # 10KB
    image_quality_ratio: float = 0.01
    ffmpeg_timeout: int = 10
    
    # Padrões de arquivos temporários
    temp_patterns: List[str] = None
    
    def __post_init__(self):
        if self.temp_patterns is None:
            self.temp_patterns = [
                '*.mp4', '*.webm', '*.mkv', '*.avi', '*.mov',
                '*.jpg', '*.jpeg', '*.png', '*.webp', '*.gif',
                '*_thumb.jpg', '*_part*.mp4', '*_cut*.mp4',
                '*_img*.jpg', '*_img*.png', '*_story*.*',
                '*_compressed.*', '*_watermarked.*'
            ]


class ProgressIndicator:
    """Classe para indicadores de progresso e feedback visual."""
    
    def __init__(self, config: UtilsConfig):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Emojis para diferentes estados
        self.status_emojis = {
            'starting': '🚀',
            'downloading': '⬇️',
            'processing': '⚙️',
            'uploading': '⬆️',
            'completed': '✅',
            'error': '❌',
            'warning': '⚠️',
            'info': 'ℹ️',
            'success': '🎉',
            'cancelled': '🚫'
        }
        
        # Emojis animados para loading
        self.loading_emojis = ['⏳', '⌛', '🔄', '⚡', '💫', '✨']
    
    def create_progress_bar(self, percentage: float, length: Optional[int] = None) -> str:
        """Cria barra de progresso visual melhorada."""
        if length is None:
            length = self.config.progress_bar_length
        
        # Garante que percentage está entre 0 e 100
        percentage = max(0, min(100, percentage))
        
        filled = int(length * percentage / 100)
        bar = '█' * filled + '░' * (length - filled)
        
        # Adiciona indicador de porcentagem com cores
        if percentage == 100:
            return f"[{bar}] {percentage:.0f}% ✅"
        elif percentage >= 75:
            return f"[{bar}] {percentage:.0f}% 🟢"
        elif percentage >= 50:
            return f"[{bar}] {percentage:.0f}% 🟡"
        elif percentage >= 25:
            return f"[{bar}] {percentage:.0f}% 🟠"
        else:
            return f"[{bar}] {percentage:.0f}% 🔴"
    
    def get_loading_emoji(self, step: int = 0) -> str:
        """Retorna emoji animado para loading."""
        return self.loading_emojis[step % len(self.loading_emojis)]
    
    def get_status_emoji(self, status: str) -> str:
        """Retorna emoji baseado no status."""
        return self.status_emojis.get(status.lower(), '📱')
    
    async def send_progress_message(
        self, 
        context, 
        chat_id: int, 
        message: str, 
        status: str = 'info', 
        progress: Optional[float] = None,
        extra_info: Optional[str] = None
    ) -> bool:
        """Envia mensagem de progresso com feedback visual melhorado."""
        try:
            emoji = self.get_status_emoji(status)
            
            # Monta a mensagem
            text_parts = [f"{emoji} **{message}**"]
            
            # Adiciona barra de progresso se fornecida
            if progress is not None:
                progress_bar = self.create_progress_bar(progress)
                text_parts.append(f"\n{progress_bar}")
            
            # Adiciona informações extras
            if extra_info:
                text_parts.append(f"\n\n{extra_info}")
            
            text = "".join(text_parts)
            
            await context.bot.send_message(
                chat_id,
                text=text,
                parse_mode='Markdown'
            )
            
            return True
            
        except Exception as e:
            self.logger.error(f"Erro ao enviar mensagem de progresso: {e}")
            return False
    
    def format_file_size(self, size_bytes: int) -> str:
        """Formata tamanho de arquivo em formato legível."""
        if size_bytes == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        size = float(size_bytes)
        
        while size >= 1024.0 and i < len(size_names) - 1:
            size /= 1024.0
            i += 1
        
        return f"{size:.1f} {size_names[i]}"
    
    def format_duration(self, seconds: int) -> str:
        """Formata duração em formato legível."""
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            minutes = seconds // 60
            secs = seconds % 60
            return f"{minutes}m {secs}s"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours}h {minutes}m"


class MediaValidator:
    """Classe para validação de mídia e URLs."""
    
    def __init__(self, config: UtilsConfig):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Cache para validações custosas
        self._image_cache: Dict[str, bool] = {}
        self._url_cache: Dict[str, Dict[str, bool]] = {}
    
    def is_good_quality_image(self, image_path: str, use_cache: bool = True) -> bool:
        """Verifica se a imagem tem boa qualidade."""
        # Verifica cache primeiro
        if use_cache and image_path in self._image_cache:
            return self._image_cache[image_path]
        
        try:
            if not os.path.exists(image_path):
                return False
            
            with Image.open(image_path) as img:
                width, height = img.size
                file_size = os.path.getsize(image_path)
                
                # Critérios de qualidade melhorados
                min_width, min_height = self.config.image_min_resolution
                min_resolution = width >= min_width and height >= min_height
                min_file_size = file_size >= self.config.image_min_file_size
                
                # Verifica ratio de qualidade (evita imagens muito comprimidas)
                quality_ratio = file_size / (width * height) if (width * height) > 0 else 0
                good_ratio = quality_ratio > self.config.image_quality_ratio
                
                # Verifica se não é uma imagem corrompida
                try:
                    img.verify()
                    not_corrupted = True
                except Exception:
                    not_corrupted = False
                
                result = min_resolution and min_file_size and good_ratio and not_corrupted
                
                # Armazena no cache
                if use_cache:
                    self._image_cache[image_path] = result
                
                return result
                
        except Exception as e:
            self.logger.warning(f"Erro ao verificar qualidade da imagem {image_path}: {e}")
            return False
    
    def is_story_url(self, url: str) -> bool:
        """Detecta se a URL é de um Story."""
        story_patterns = [
            '/stories/',
            '/story/',
            'instagram.com/stories/',
            'facebook.com/stories/',
            'fb.watch/story/',
            'm.facebook.com/story',
            'web.facebook.com/stories'
        ]
        
        url_lower = url.lower()
        return any(pattern in url_lower for pattern in story_patterns)
    
    def is_valid_url(self, url: str) -> bool:
        """Valida se a URL tem formato válido."""
        try:
            from urllib.parse import urlparse
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except Exception:
            return False
    
    def get_url_domain(self, url: str) -> Optional[str]:
        """Extrai domínio da URL."""
        try:
            from urllib.parse import urlparse
            return urlparse(url).netloc.lower()
        except Exception:
            return None
    
    def clear_cache(self) -> None:
        """Limpa cache de validações."""
        self._image_cache.clear()
        self._url_cache.clear()
        self.logger.info("Cache de validações limpo")


class TimeUtils:
    """Utilitários para manipulação de tempo."""
    
    @staticmethod
    def parse_time_to_seconds(time_str: str) -> int:
        """Converte string de tempo para segundos com validação melhorada."""
        try:
            time_str = time_str.strip().lower()
            
            # Se já é um número (segundos)
            if time_str.isdigit():
                return int(time_str)
            
            # Remove caracteres não numéricos exceto ':'
            clean_time = ''.join(c for c in time_str if c.isdigit() or c == ':')
            
            # Formato HH:MM:SS
            if clean_time.count(':') == 2:
                parts = clean_time.split(':')
                if len(parts) == 3 and all(part.isdigit() for part in parts):
                    h, m, s = map(int, parts)
                    if 0 <= h <= 23 and 0 <= m <= 59 and 0 <= s <= 59:
                        return h * 3600 + m * 60 + s
            
            # Formato MM:SS
            elif clean_time.count(':') == 1:
                parts = clean_time.split(':')
                if len(parts) == 2 and all(part.isdigit() for part in parts):
                    m, s = map(int, parts)
                    if 0 <= m <= 59 and 0 <= s <= 59:
                        return m * 60 + s
            
            raise ValueError(f"Formato inválido: {time_str}")
            
        except Exception as e:
            raise ValueError(f"Erro ao converter tempo '{time_str}': {str(e)}")
    
    @staticmethod
    def format_seconds_to_time(seconds: int) -> str:
        """Converte segundos para formato HH:MM:SS ou MM:SS."""
        if seconds < 0:
            return "00:00"
        
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes:02d}:{secs:02d}"
    
    @staticmethod
    def get_timestamp() -> str:
        """Retorna timestamp atual formatado."""
        return datetime.now().strftime("%Y%m%d_%H%M%S")
    
    @staticmethod
    def is_file_old(file_path: str, max_age_seconds: int) -> bool:
        """Verifica se arquivo é mais antigo que o limite especificado."""
        try:
            if not os.path.exists(file_path):
                return True
            
            file_time = os.path.getmtime(file_path)
            current_time = time.time()
            return (current_time - file_time) > max_age_seconds
        except Exception:
            return True


class FileManager:
    """Gerenciador de arquivos e limpeza."""
    
    def __init__(self, config: UtilsConfig):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def cleanup_temp_files(self, force: bool = False) -> int:
        """Remove arquivos temporários com opção de limpeza forçada."""
        try:
            removed_count = 0
            current_time = time.time()
            
            for pattern in self.config.temp_patterns:
                for file_path in glob.glob(pattern):
                    try:
                        should_remove = force
                        
                        if not force:
                            # Verifica idade do arquivo
                            file_time = os.path.getmtime(file_path)
                            should_remove = (current_time - file_time) > self.config.temp_file_max_age
                        
                        if should_remove:
                            os.remove(file_path)
                            removed_count += 1
                            self.logger.info(f"Arquivo removido: {file_path}")
                            
                    except Exception as e:
                        self.logger.warning(f"Erro ao remover {file_path}: {e}")
            
            action = "forçada" if force else "automática"
            self.logger.info(f"Limpeza {action} concluída: {removed_count} arquivos removidos")
            return removed_count
            
        except Exception as e:
            self.logger.error(f"Erro na limpeza de arquivos: {e}")
            return 0
    
    def get_temp_files_info(self) -> Dict[str, Union[int, List[str]]]:
        """Retorna informações sobre arquivos temporários."""
        try:
            files = []
            total_size = 0
            current_time = time.time()
            
            for pattern in self.config.temp_patterns:
                for file_path in glob.glob(pattern):
                    try:
                        file_size = os.path.getsize(file_path)
                        file_time = os.path.getmtime(file_path)
                        age_hours = (current_time - file_time) / 3600
                        
                        files.append({
                            'path': file_path,
                            'size': file_size,
                            'age_hours': age_hours
                        })
                        total_size += file_size
                        
                    except Exception as e:
                        self.logger.warning(f"Erro ao analisar {file_path}: {e}")
            
            return {
                'count': len(files),
                'total_size': total_size,
                'files': files
            }
            
        except Exception as e:
            self.logger.error(f"Erro ao obter informações de arquivos: {e}")
            return {'count': 0, 'total_size': 0, 'files': []}
    
    def create_temp_filename(self, chat_id: int, prefix: str, extension: str) -> str:
        """Cria nome de arquivo temporário único."""
        timestamp = TimeUtils.get_timestamp()
        return f"{chat_id}_{timestamp}_{prefix}.{extension.lstrip('.')}"
    
    def ensure_directory(self, directory: str) -> bool:
        """Garante que diretório existe."""
        try:
            Path(directory).mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            self.logger.error(f"Erro ao criar diretório {directory}: {e}")
            return False


class SystemUtils:
    """Utilitários do sistema."""
    
    def __init__(self, config: UtilsConfig):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self._ffmpeg_available: Optional[bool] = None
    
    async def check_ffmpeg(self, force_check: bool = False) -> bool:
        """Verifica se FFmpeg está disponível com cache."""
        if self._ffmpeg_available is not None and not force_check:
            return self._ffmpeg_available
        
        try:
            process = await asyncio.create_subprocess_exec(
                'ffmpeg', '-version',
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            try:
                await asyncio.wait_for(process.communicate(), timeout=self.config.ffmpeg_timeout)
                self._ffmpeg_available = process.returncode == 0
            except asyncio.TimeoutError:
                process.kill()
                self._ffmpeg_available = False
            
            return self._ffmpeg_available
            
        except Exception as e:
            self.logger.warning(f"Erro ao verificar FFmpeg: {e}")
            self._ffmpeg_available = False
            return False
    
    def get_system_info(self) -> Dict[str, Union[str, int, float]]:
        """Retorna informações do sistema."""
        try:
            import platform
            import psutil
            
            return {
                'platform': platform.system(),
                'platform_version': platform.version(),
                'python_version': platform.python_version(),
                'cpu_count': os.cpu_count(),
                'memory_total': psutil.virtual_memory().total,
                'memory_available': psutil.virtual_memory().available,
                'disk_free': psutil.disk_usage('.').free
            }
        except ImportError:
            return {
                'platform': 'Unknown',
                'cpu_count': os.cpu_count() or 1
            }
        except Exception as e:
            self.logger.error(f"Erro ao obter informações do sistema: {e}")
            return {}


# Classes principais para uso externo
class Utils:
    """Classe principal que agrupa todas as utilidades."""
    
    def __init__(self, config: Optional[UtilsConfig] = None):
        self.config = config or UtilsConfig()
        
        self.progress = ProgressIndicator(self.config)
        self.validator = MediaValidator(self.config)
        self.time = TimeUtils()
        self.files = FileManager(self.config)
        self.system = SystemUtils(self.config)
        
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def clear_all_caches(self) -> None:
        """Limpa todos os caches."""
        self.validator.clear_cache()
        self.system._ffmpeg_available = None
        self.logger.info("Todos os caches limpos")


# Funções de compatibilidade para manter API existente
_utils_instance = Utils()

# Progress functions
create_progress_bar = _utils_instance.progress.create_progress_bar
get_loading_emoji = _utils_instance.progress.get_loading_emoji
get_status_emoji = _utils_instance.progress.get_status_emoji
send_progress_message = _utils_instance.progress.send_progress_message

# Validation functions
is_good_quality_image = _utils_instance.validator.is_good_quality_image
is_story_url = _utils_instance.validator.is_story_url

# Time functions
parse_time_to_seconds = _utils_instance.time.parse_time_to_seconds
format_seconds_to_time = _utils_instance.time.format_seconds_to_time

# File functions
cleanup_temp_files = _utils_instance.files.cleanup_temp_files
force_cleanup_temp_files = lambda: _utils_instance.files.cleanup_temp_files(force=True)

# System functions
check_ffmpeg = _utils_instance.system.check_ffmpeg