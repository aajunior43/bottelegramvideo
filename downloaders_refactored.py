#!/usr/bin/env python3
"""
Downloaders Refatorados - Versão 2.1.0

Melhorias implementadas:
- Separação em classes especializadas
- Melhor tratamento de erros
- Configuração centralizada
- Métodos mais focados e reutilizáveis
- Logging estruturado
- Validação de entrada
"""

import asyncio
import logging
import os
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

from utils import (
    send_progress_message, 
    is_good_quality_image, 
    is_story_url,
    check_ffmpeg
)


@dataclass
class VideoQuality:
    """Representa uma qualidade de vídeo disponível."""
    format_id: str
    quality: str
    filesize: Optional[int] = None
    fps: Optional[int] = None
    codec: Optional[str] = None


@dataclass
class DownloadConfig:
    """Configuração para downloads."""
    max_file_size: int = 40 * 1024 * 1024  # 40MB
    max_compressed_size: int = 30 * 1024 * 1024  # 30MB
    timeout: int = 300
    temp_dir: str = "./temp"
    
    def __post_init__(self):
        """Cria diretório temporário se não existir."""
        Path(self.temp_dir).mkdir(exist_ok=True)


class BaseDownloader(ABC):
    """Classe base para todos os downloaders."""
    
    def __init__(self, config: DownloadConfig):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
    
    @abstractmethod
    async def download(self, url: str, chat_id: int, context: Any) -> bool:
        """Método abstrato para download."""
        pass
    
    def _generate_output_template(self, chat_id: int, message_id: int, prefix: str) -> str:
        """Gera template de saída padronizado."""
        return f"{self.config.temp_dir}/{chat_id}_{message_id}_{prefix}_%(title)s.%(ext)s"
    
    async def _execute_command(self, command: List[str]) -> Tuple[bool, str, str]:
        """Executa comando de forma assíncrona."""
        try:
            self.logger.info(f"Executando: {' '.join(command)}")
            
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            return (
                process.returncode == 0,
                stdout.decode('utf-8', errors='ignore'),
                stderr.decode('utf-8', errors='ignore')
            )
        except Exception as e:
            self.logger.error(f"Erro ao executar comando: {e}")
            return False, "", str(e)


class VideoProcessor:
    """Classe para processamento de vídeos (compressão, divisão, etc.)."""
    
    def __init__(self, config: DownloadConfig):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
    
    async def is_ffmpeg_available(self) -> bool:
        """Verifica se FFmpeg está disponível."""
        try:
            process = await asyncio.create_subprocess_exec(
                'ffmpeg', '-version',
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            await process.communicate()
            return process.returncode == 0
        except Exception:
            return False
    
    async def get_video_duration(self, video_file: str) -> Optional[float]:
        """Obtém duração do vídeo em segundos."""
        try:
            command = [
                'ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
                '-of', 'csv=p=0', video_file
            ]
            
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                return float(stdout.decode().strip())
            return None
        except Exception as e:
            self.logger.error(f"Erro ao obter duração: {e}")
            return None
    
    async def compress_video(self, video_file: str, target_size: int, aggressive: bool = False) -> Optional[str]:
        """Comprime vídeo para o tamanho alvo."""
        if not await self.is_ffmpeg_available():
            self.logger.warning("FFmpeg não disponível para compressão")
            return None
        
        try:
            output_file = f"{video_file}_compressed.mp4"
            
            if aggressive:
                command = [
                    'ffmpeg', '-i', video_file,
                    '-vf', 'scale=640:480',
                    '-c:v', 'libx264', '-preset', 'fast',
                    '-crf', '28', '-c:a', 'aac', '-b:a', '64k',
                    '-y', output_file
                ]
            else:
                command = [
                    'ffmpeg', '-i', video_file,
                    '-c:v', 'libx264', '-preset', 'medium',
                    '-crf', '23', '-c:a', 'aac', '-b:a', '128k',
                    '-y', output_file
                ]
            
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            await process.communicate()
            
            if process.returncode == 0 and os.path.exists(output_file):
                if os.path.getsize(output_file) <= target_size:
                    self.logger.info(f"Vídeo comprimido: {os.path.getsize(output_file)/1024/1024:.1f}MB")
                    return output_file
                else:
                    os.remove(output_file)
                    self.logger.warning("Compressão não atingiu tamanho alvo")
            
            return None
            
        except Exception as e:
            self.logger.error(f"Erro na compressão: {e}")
            return None
    
    async def split_video_ffmpeg(self, video_file: str, max_size: int) -> List[str]:
        """Divide vídeo usando FFmpeg mantendo formato válido."""
        if not await self.is_ffmpeg_available():
            return []
        
        try:
            duration = await self.get_video_duration(video_file)
            if not duration:
                return []
            
            file_size = os.path.getsize(video_file)
            num_parts = (file_size + max_size - 1) // max_size
            part_duration = duration / num_parts
            
            parts = []
            base_name = os.path.splitext(video_file)[0]
            
            for i in range(int(num_parts)):
                start_time = i * part_duration
                part_file = f"{base_name}_part{i+1}.mp4"
                
                command = [
                    'ffmpeg', '-i', video_file, '-ss', str(start_time),
                    '-t', str(part_duration), '-c', 'copy', '-y', part_file
                ]
                
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                
                await process.communicate()
                
                if process.returncode == 0 and os.path.exists(part_file):
                    parts.append(part_file)
                    self.logger.info(f"Parte criada: {part_file} ({os.path.getsize(part_file)/1024/1024:.1f}MB)")
            
            return parts
            
        except Exception as e:
            self.logger.error(f"Erro na divisão com FFmpeg: {e}")
            return []
    
    async def split_file_binary(self, file_path: str, max_size: int) -> List[str]:
        """Divide arquivo usando divisão binária simples."""
        try:
            file_size = os.path.getsize(file_path)
            if file_size <= max_size:
                return [file_path]
            
            num_parts = (file_size + max_size - 1) // max_size
            parts = []
            base_name = os.path.splitext(file_path)[0]
            
            with open(file_path, 'rb') as source:
                for i in range(num_parts):
                    part_file = f"{base_name}_part{i+1}.mp4"
                    
                    start_pos = i * max_size
                    remaining = file_size - start_pos
                    part_size = min(max_size, remaining)
                    
                    source.seek(start_pos)
                    data = source.read(part_size)
                    
                    with open(part_file, 'wb') as part:
                        part.write(data)
                    
                    if os.path.exists(part_file) and os.path.getsize(part_file) > 0:
                        parts.append(part_file)
                        self.logger.info(f"Parte binária criada: {part_file} ({os.path.getsize(part_file)/1024/1024:.1f}MB)")
            
            return parts
            
        except Exception as e:
            self.logger.error(f"Erro na divisão binária: {e}")
            return [file_path]
    
    async def generate_thumbnail(self, video_file: str) -> Optional[str]:
        """Gera thumbnail do vídeo."""
        if not await self.is_ffmpeg_available():
            return None
        
        try:
            thumbnail_file = f"{video_file}_thumb.jpg"
            command = [
                'ffmpeg', '-i', video_file, '-ss', '00:00:01.000',
                '-vframes', '1', '-y', thumbnail_file
            ]
            
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            await process.communicate()
            
            if process.returncode == 0 and os.path.exists(thumbnail_file):
                return thumbnail_file
            return None
            
        except Exception as e:
            self.logger.error(f"Erro ao gerar thumbnail: {e}")
            return None


class VideoSender:
    """Classe responsável por enviar vídeos via Telegram."""
    
    def __init__(self, config: DownloadConfig):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self.processor = VideoProcessor(config)
    
    async def send_video_with_fallback(self, chat_id: int, video_file: str, context: Any, caption: str = "") -> bool:
        """Envia vídeo com fallback para documento e processamento automático."""
        try:
            file_size = os.path.getsize(video_file)
            
            # Se arquivo muito grande, processa primeiro
            if file_size > self.config.max_file_size:
                return await self._handle_large_file(chat_id, video_file, context, caption)
            
            # Tenta enviar normalmente
            return await self._send_video_direct(chat_id, video_file, context, caption)
            
        except Exception as e:
            self.logger.error(f"Erro ao enviar vídeo: {e}")
            return False
    
    async def _handle_large_file(self, chat_id: int, video_file: str, context: Any, caption: str) -> bool:
        """Processa arquivos grandes (compressão ou divisão)."""
        self.logger.info(f"Arquivo grande detectado: {os.path.getsize(video_file)/1024/1024:.1f}MB")
        
        # Tenta compressão primeiro
        compressed_file = await self.processor.compress_video(video_file, self.config.max_file_size)
        if compressed_file:
            success = await self._send_video_direct(chat_id, compressed_file, context, f"{caption} (Comprimido)")
            os.remove(compressed_file)
            return success
        
        # Se compressão falhar, divide arquivo
        await context.bot.send_message(chat_id, "📹 Arquivo muito grande, dividindo em partes...")
        
        # Tenta divisão com FFmpeg primeiro
        parts = await self.processor.split_video_ffmpeg(video_file, self.config.max_file_size)
        if not parts:
            # Fallback para divisão binária
            parts = await self.processor.split_file_binary(video_file, self.config.max_file_size)
        
        if parts:
            success = True
            for i, part in enumerate(parts, 1):
                part_caption = f"{caption} - Parte {i}/{len(parts)}"
                part_success = await self._send_video_part(chat_id, part, context, part_caption)
                if not part_success:
                    success = False
                os.remove(part)
            return success
        
        await context.bot.send_message(chat_id, "❌ Não foi possível processar o arquivo")
        return False
    
    async def _send_video_direct(self, chat_id: int, video_file: str, context: Any, caption: str) -> bool:
        """Envia vídeo diretamente."""
        try:
            # Gera thumbnail
            thumbnail_file = await self.processor.generate_thumbnail(video_file)
            
            with open(video_file, 'rb') as video:
                if thumbnail_file:
                    with open(thumbnail_file, 'rb') as thumb:
                        await context.bot.send_video(
                            chat_id,
                            video=video,
                            thumbnail=thumb,
                            supports_streaming=True,
                            caption=caption,
                            read_timeout=self.config.timeout,
                            write_timeout=self.config.timeout
                        )
                else:
                    await context.bot.send_video(
                        chat_id,
                        video=video,
                        supports_streaming=True,
                        caption=caption,
                        read_timeout=self.config.timeout,
                        write_timeout=self.config.timeout
                    )
            
            # Remove thumbnail temporário
            if thumbnail_file and os.path.exists(thumbnail_file):
                os.remove(thumbnail_file)
            
            return True
            
        except Exception as e:
            self.logger.warning(f"Erro ao enviar como vídeo: {e}")
            
            # Fallback para documento
            if "too large" not in str(e).lower():
                return await self._send_as_document(chat_id, video_file, context, caption)
            
            return False
    
    async def _send_video_part(self, chat_id: int, video_file: str, context: Any, caption: str) -> bool:
        """Envia uma parte do vídeo."""
        try:
            with open(video_file, 'rb') as video:
                await context.bot.send_video(
                    chat_id,
                    video=video,
                    caption=caption,
                    supports_streaming=True,
                    read_timeout=self.config.timeout,
                    write_timeout=self.config.timeout
                )
            return True
        except Exception as e:
            self.logger.warning(f"Erro ao enviar parte como vídeo: {e}")
            return await self._send_as_document(chat_id, video_file, context, caption)
    
    async def _send_as_document(self, chat_id: int, file_path: str, context: Any, caption: str) -> bool:
        """Envia arquivo como documento."""
        try:
            filename = f"{caption.replace('/', '_')}.mp4"
            with open(file_path, 'rb') as file:
                await context.bot.send_document(
                    chat_id,
                    document=file,
                    filename=filename,
                    read_timeout=self.config.timeout,
                    write_timeout=self.config.timeout
                )
            return True
        except Exception as e:
            self.logger.error(f"Erro ao enviar como documento: {e}")
            return False


class StoryDownloader(BaseDownloader):
    """Downloader específico para Stories do Instagram/Facebook."""
    
    async def download(self, url: str, chat_id: int, context: Any, message_id: int = 0) -> bool:
        """Baixa Stories do Instagram/Facebook."""
        if not is_story_url(url):
            await send_progress_message(
                context, chat_id,
                "Esta URL não parece ser de um Story\n\n💡 Tente com um link de Story do Instagram ou Facebook",
                'warning'
            )
            return False
        
        try:
            await send_progress_message(context, chat_id, "Baixando Story", 'downloading', 0)
            
            output_template = self._generate_output_template(chat_id, message_id, "story")
            
            command = [
                'yt-dlp',
                '--write-thumbnail',
                '--write-all-thumbnails',
                '-f', 'best[height<=1080]/best',
                '--merge-output-format', 'mp4',
                '-o', output_template,
                url
            ]
            
            success, stdout, stderr = await self._execute_command(command)
            
            if success:
                return await self._process_story_files(chat_id, message_id, context)
            else:
                await send_progress_message(
                    context, chat_id,
                    f"Erro ao baixar Story\n\nPossíveis causas:\n• Story expirado (24h)\n• Story privado\n• URL inválida",
                    'error'
                )
                return False
                
        except Exception as e:
            self.logger.error(f"Erro no download de Story: {e}")
            await send_progress_message(
                context, chat_id,
                f"Erro inesperado: {str(e)[:100]}...",
                'error'
            )
            return False
    
    async def _process_story_files(self, chat_id: int, message_id: int, context: Any) -> bool:
        """Processa e envia arquivos de Story baixados."""
        try:
            # Procura arquivos baixados
            downloaded_files = []
            for file in os.listdir(self.config.temp_dir):
                if file.startswith(f"{chat_id}_{message_id}_story"):
                    downloaded_files.append(os.path.join(self.config.temp_dir, file))
            
            if not downloaded_files:
                await send_progress_message(
                    context, chat_id,
                    "Nenhum arquivo encontrado\n\n💡 Verifique se o Story ainda está disponível",
                    'warning'
                )
                return False
            
            await send_progress_message(
                context, chat_id,
                f"Story baixado com sucesso\n\n📁 {len(downloaded_files)} arquivo(s) encontrado(s)",
                'processing', 50
            )
            
            # Separa vídeos e imagens
            videos = [f for f in downloaded_files if f.endswith(('.mp4', '.webm', '.mkv'))]
            images = [f for f in downloaded_files if f.endswith(('.jpg', '.jpeg', '.png', '.webp'))]
            
            sender = VideoSender(self.config)
            
            # Envia vídeos
            for video_file in videos:
                await sender.send_video_with_fallback(chat_id, video_file, context, "Story")
                os.remove(video_file)
            
            # Envia imagens
            for image_file in images:
                try:
                    with open(image_file, 'rb') as img:
                        await context.bot.send_photo(chat_id, photo=img, caption="📱 Story")
                    os.remove(image_file)
                except Exception as e:
                    self.logger.error(f"Erro ao enviar imagem: {e}")
            
            # Remove arquivos restantes
            for file in downloaded_files:
                if os.path.exists(file):
                    try:
                        os.remove(file)
                    except Exception as e:
                        self.logger.warning(f"Erro ao remover {file}: {e}")
            
            await send_progress_message(
                context, chat_id,
                "Story enviado com sucesso",
                'completed', 100
            )
            
            return True
            
        except Exception as e:
            self.logger.error(f"Erro ao processar arquivos de Story: {e}")
            return False


class QualityManager:
    """Gerenciador de qualidades de vídeo."""
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
    
    async def get_available_qualities(self, url: str) -> List[VideoQuality]:
        """Obtém qualidades disponíveis para um vídeo."""
        try:
            command = ['yt-dlp', '--list-formats', '--no-download', url]
            
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                return self._parse_qualities(stdout.decode('utf-8', errors='ignore'))
            
            return []
            
        except Exception as e:
            self.logger.error(f"Erro ao obter qualidades: {e}")
            return []
    
    def _parse_qualities(self, output: str) -> List[VideoQuality]:
        """Parse da saída do yt-dlp para extrair qualidades."""
        qualities = []
        lines = output.split('\n')
        
        for line in lines:
            if 'mp4' in line and ('x' in line or 'p' in line):
                parts = line.split()
                if len(parts) >= 3:
                    format_id = parts[0]
                    quality_info = ' '.join(parts[1:4])
                    qualities.append(VideoQuality(
                        format_id=format_id,
                        quality=quality_info
                    ))
        
        return qualities[:5]  # Retorna até 5 qualidades
    
    async def is_playlist(self, url: str) -> bool:
        """Verifica se URL contém múltiplos vídeos."""
        try:
            command = [
                'yt-dlp', '--flat-playlist', '--no-download',
                '--print', 'title', url
            ]
            
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                output = stdout.decode('utf-8', errors='ignore')
                videos = [line.strip() for line in output.split('\n') if line.strip()]
                return len(videos) > 1
            
            return False
            
        except Exception as e:
            self.logger.error(f"Erro ao verificar playlist: {e}")
            return False


# Funções de conveniência para compatibilidade
async def download_story(update, context, url=None):
    """Função de compatibilidade para download de stories."""
    config = DownloadConfig()
    downloader = StoryDownloader(config)
    
    chat_id = update.message.chat_id
    message_id = update.message.message_id
    
    if url is None:
        if context.args:
            url = context.args[0]
        else:
            await send_progress_message(
                context, chat_id,
                "Uso correto: /story [URL]\n\nExemplo: /story https://instagram.com/stories/usuario/123",
                'info'
            )
            return
    
    await downloader.download(url, chat_id, context, message_id)


async def send_video_with_fallback(chat_id, video_file, context, caption=""):
    """Função de compatibilidade para envio de vídeos."""
    config = DownloadConfig()
    sender = VideoSender(config)
    return await sender.send_video_with_fallback(chat_id, video_file, context, caption)


async def get_video_qualities(url):
    """Função de compatibilidade para obter qualidades."""
    manager = QualityManager()
    qualities = await manager.get_available_qualities(url)
    return [{'format_id': q.format_id, 'quality': q.quality} for q in qualities]


async def list_available_videos(url):
    """Função de compatibilidade para verificar playlists."""
    manager = QualityManager()
    return await manager.is_playlist(url)


async def split_file_by_size(video_file, max_size_bytes):
    """Função de compatibilidade para divisão de arquivos."""
    config = DownloadConfig()
    processor = VideoProcessor(config)
    return await processor.split_file_binary(video_file, max_size_bytes)