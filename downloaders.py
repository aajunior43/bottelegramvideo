import asyncio
import logging
import os
import subprocess
from datetime import datetime
from utils import (
    send_progress_message, 
    is_good_quality_image, 
    is_story_url,
    check_ffmpeg
)

# Configura o logger
logger = logging.getLogger(__name__)

# Funções de Download de Vídeo
async def split_video_with_ytdlp(video_url, chat_id, message_id, max_size_bytes):
    """Divide vídeo em partes usando yt-dlp e ffmpeg."""
    try:
        # Template para partes do vídeo
        output_template = f"{chat_id}_{message_id}_part%(autonumber)s.%(ext)s"
        
        # Comando yt-dlp com divisão por tamanho
        command = [
            'yt-dlp',
            '--format', f'best[filesize<{max_size_bytes}]/best',
            '--output', output_template,
            video_url
        ]
        
        # Executa o comando
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            # Procura por arquivos de partes
            video_parts = []
            for file in os.listdir('.'):
                if file.startswith(f"{chat_id}_{message_id}_part") and file.endswith('.mp4'):
                    video_parts.append(file)
            
            return sorted(video_parts)
        else:
            logger.error(f"Erro no yt-dlp para partes: {stderr.decode()}")
            return []
            
    except Exception as e:
        logger.error(f"Erro na função split_video_with_ytdlp: {e}")
        return []

async def split_file_by_size(video_file, max_size_bytes):
    """Divide um arquivo de vídeo em partes menores usando ffmpeg."""
    try:
        file_size = os.path.getsize(video_file)
        
        if file_size <= max_size_bytes:
            return [video_file]
        
        # Calcula número de partes necessárias
        num_parts = (file_size // max_size_bytes) + 1
        
        # Obtém duração do vídeo
        duration_cmd = [
            'ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
            '-of', 'csv=p=0', video_file
        ]
        
        process = await asyncio.create_subprocess_exec(
            *duration_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            return [video_file]
        
        total_duration = float(stdout.decode().strip())
        part_duration = total_duration / num_parts
        
        video_parts = []
        base_name = os.path.splitext(video_file)[0]
        
        for i in range(int(num_parts)):
            start_time = i * part_duration
            part_file = f"{base_name}_part{i+1}.mp4"
            
            split_cmd = [
                'ffmpeg', '-i', video_file, '-ss', str(start_time),
                '-t', str(part_duration), '-c', 'copy', '-y', part_file
            ]
            
            process = await asyncio.create_subprocess_exec(
                *split_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            await process.communicate()
            
            if process.returncode == 0 and os.path.exists(part_file):
                video_parts.append(part_file)
        
        return video_parts
        
    except Exception as e:
        logger.error(f"Erro na função split_file_by_size: {e}")
        return [video_file]

# Funções de Download de Stories
async def download_story(update, context, url=None):
    """Baixa Stories do Instagram/Facebook."""
    try:
        chat_id = update.message.chat_id
        message_id = update.message.message_id
        
        # Obtém URL dos argumentos ou da mensagem
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
        
        # Verifica se é realmente um Story
        if not is_story_url(url):
            await send_progress_message(
                context, chat_id,
                "Esta URL não parece ser de um Story\n\n💡 Tente com um link de Story do Instagram ou Facebook",
                'warning'
            )
            return
        
        # Inicia o download
        await send_progress_message(context, chat_id, "Baixando Story", 'downloading', 0)
        
        # Template de saída
        output_template = f"{chat_id}_{message_id}_story%(autonumber)s.%(ext)s"
        
        # Comando yt-dlp simplificado para Stories
        command = [
            'yt-dlp',
            '--write-thumbnail',
            '--write-all-thumbnails',
            '-f', 'best[height<=1080]/best',
            '--merge-output-format', 'mp4',
            '-o', output_template,
            url
        ]
        
        logger.info(f"Executando comando para Story: {' '.join(command)}")
        
        # Executa o comando de forma assíncrona
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            # Procura por arquivos baixados
            downloaded_files = []
            for file in os.listdir('.'):
                if file.startswith(f"{chat_id}_{message_id}_story"):
                    downloaded_files.append(file)
            
            if downloaded_files:
                await send_progress_message(
                    context, chat_id,
                    f"Story baixado com sucesso\n\n📁 {len(downloaded_files)} arquivo(s) encontrado(s)",
                    'processing',
                    50
                )
                
                # Separa vídeos e imagens
                videos = [f for f in downloaded_files if f.endswith(('.mp4', '.webm', '.mkv'))]
                images = [f for f in downloaded_files if f.endswith(('.jpg', '.jpeg', '.png', '.webp'))]
                
                # Envia vídeos
                for video_file in videos:
                    try:
                        await send_video_with_fallback(chat_id, video_file, context, "Story")
                        os.remove(video_file)
                        logger.info(f"Story vídeo enviado e removido: {video_file}")
                    except Exception as e:
                        logger.error(f"Erro ao enviar story vídeo {video_file}: {e}")
                
                # Envia imagens
                for image_file in images:
                    try:
                        with open(image_file, 'rb') as img:
                            await context.bot.send_photo(
                                chat_id,
                                photo=img,
                                caption="📱 Story"
                            )
                        os.remove(image_file)
                        logger.info(f"Story imagem enviada e removida: {image_file}")
                    except Exception as e:
                        logger.error(f"Erro ao enviar story imagem {image_file}: {e}")
                
                # Remove arquivos restantes
                for file in downloaded_files:
                    try:
                        if os.path.exists(file):
                            os.remove(file)
                    except Exception as e:
                        logger.warning(f"Erro ao remover {file}: {e}")
                
                await send_progress_message(
                    context, chat_id,
                    "Story enviado com sucesso",
                    'completed',
                    100
                )
            else:
                await send_progress_message(
                    context, chat_id,
                    "Nenhum arquivo encontrado\n\n💡 Verifique se o Story ainda está disponível",
                    'warning'
                )
        else:
            error_message = stderr.decode('utf-8', errors='ignore')
            logger.error(f"Erro no yt-dlp para Story: {error_message}")
            
            await send_progress_message(
                context, chat_id,
                f"Erro ao baixar Story\n\nPossíveis causas:\n• Story expirado (24h)\n• Story privado\n• URL inválida\n\nErro técnico: `{error_message.splitlines()[-1] if error_message.splitlines() else 'Erro desconhecido'}`",
                'error'
            )
            
    except Exception as e:
        logger.error(f"Erro inesperado no download de Story: {e}")
        await send_progress_message(
            context, chat_id,
            f"Erro inesperado\n\nDetalhes: {str(e)[:100]}...",
            'error'
        )

# Função auxiliar para envio de vídeos
async def send_video_with_fallback(chat_id, video_file, context, caption=""):
    """Envia vídeo com fallback para documento em caso de timeout."""
    try:
        # Gera thumbnail do vídeo usando ffmpeg
        thumbnail_file = None
        try:
            thumbnail_file = f"{video_file}_thumb.jpg"
            ffmpeg_cmd = [
                'ffmpeg', '-i', video_file, '-ss', '00:00:01.000', 
                '-vframes', '1', '-y', thumbnail_file
            ]
            
            process = await asyncio.create_subprocess_exec(
                *ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            await process.communicate()
            
            # Verifica se o thumbnail foi criado
            if not os.path.exists(thumbnail_file):
                thumbnail_file = None
        except Exception as thumb_error:
            logger.warning(f"Erro ao gerar thumbnail: {thumb_error}")
            thumbnail_file = None
        
        # Envia o vídeo com thumbnail se disponível
        with open(video_file, 'rb') as video:
            if thumbnail_file and os.path.exists(thumbnail_file):
                with open(thumbnail_file, 'rb') as thumb:
                    await context.bot.send_video(
                        chat_id,
                        video=video,
                        thumbnail=thumb,
                        supports_streaming=True,
                        caption=caption,
                        read_timeout=300,
                        write_timeout=300,
                        connect_timeout=60
                    )
            else:
                await context.bot.send_video(
                    chat_id,
                    video=video,
                    supports_streaming=True,
                    caption=caption,
                    read_timeout=300,
                    write_timeout=300,
                    connect_timeout=60
                )
        
        # Remove o thumbnail temporário
        if thumbnail_file and os.path.exists(thumbnail_file):
            os.remove(thumbnail_file)
            
    except Exception as video_error:
        if "timed out" in str(video_error).lower() or "timeout" in str(video_error).lower():
            logger.warning(f"Timeout ao enviar {video_file}, enviando como documento")
            await context.bot.send_message(chat_id, text=f"⏰ Timeout no {caption.lower()}, enviando como documento...")
        else:
            logger.warning(f"Erro ao enviar {video_file} como vídeo: {video_error}")
        
        with open(video_file, 'rb') as video:
            await context.bot.send_document(
                chat_id,
                document=video,
                filename=f"{caption.replace('/', '_')}.mp4",
                read_timeout=300,
                write_timeout=300
            )

# Funções de listagem e qualidade
async def list_available_videos(url):
    """Lista vídeos disponíveis em uma URL."""
    try:
        command = [
            'yt-dlp',
            '--flat-playlist',
            '--no-download',
            '--print', 'title',
            url
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
        logger.error(f"Erro ao listar vídeos: {e}")
        return False

async def get_video_qualities(url):
    """Obtém as qualidades disponíveis para um vídeo."""
    try:
        command = [
            'yt-dlp',
            '--list-formats',
            '--no-download',
            url
        ]
        
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            output = stdout.decode('utf-8', errors='ignore')
            
            # Parse das qualidades (simplificado)
            qualities = []
            lines = output.split('\n')
            
            for line in lines:
                if 'mp4' in line and ('x' in line or 'p' in line):
                    parts = line.split()
                    if len(parts) >= 3:
                        format_id = parts[0]
                        quality_info = ' '.join(parts[1:4])
                        qualities.append({
                            'format_id': format_id,
                            'quality': quality_info
                        })
            
            return qualities[:5]  # Retorna até 5 qualidades
        
        return []
        
    except Exception as e:
        logger.error(f"Erro ao obter qualidades: {e}")
        return []