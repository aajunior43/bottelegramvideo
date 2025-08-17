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
            # Procura por arquivos gerados
            parts = []
            for file in os.listdir('.'):
                if file.startswith(f"{chat_id}_{message_id}_part"):
                    parts.append(file)
            return sorted(parts)
        else:
            logger.error(f"Erro no yt-dlp split: {stderr.decode()}")
            return []
            
    except Exception as e:
        logger.error(f"Erro na divisão com yt-dlp: {e}")
        return []

async def split_video_with_ffmpeg(video_file, max_size_bytes):
    """Divide vídeo em partes usando FFmpeg mantendo formato válido."""
    try:
        # Verifica se FFmpeg está disponível
        try:
            ffmpeg_check = await asyncio.create_subprocess_exec(
                'ffmpeg', '-version',
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            await ffmpeg_check.communicate()
            if ffmpeg_check.returncode != 0:
                return []
        except:
            return []
        
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
            return []
        
        total_duration = float(stdout.decode().strip())
        file_size = os.path.getsize(video_file)
        
        # Calcula número de partes baseado no tamanho
        num_parts = (file_size + max_size_bytes - 1) // max_size_bytes
        part_duration = total_duration / num_parts
        
        parts = []
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
                parts.append(part_file)
                logger.info(f"Parte de vídeo criada: {part_file} ({os.path.getsize(part_file)/1024/1024:.1f}MB)")
        
        return parts
        
    except Exception as e:
        logger.error(f"Erro na divisão com FFmpeg: {e}")
        return []
            
    except Exception as e:
        logger.error(f"Erro na divisão com yt-dlp: {e}")
        return []

async def compress_video(video_file, target_size, aggressive=False):
    """Comprime vídeo para o tamanho alvo."""
    try:
        # Verifica se FFmpeg está disponível
        try:
            ffmpeg_check = await asyncio.create_subprocess_exec(
                'ffmpeg', '-version',
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            await ffmpeg_check.communicate()
            ffmpeg_available = ffmpeg_check.returncode == 0
        except:
            ffmpeg_available = False
        
        if not ffmpeg_available:
            logger.warning("FFmpeg não encontrado, usando método alternativo")
            # Fallback: simplesmente retorna None para usar divisão de arquivo
            return None
        
        output_file = f"{video_file}_compressed.mp4"
        
        if aggressive:
            # Compressão mais agressiva
            command = [
                'ffmpeg', '-i', video_file,
                '-vf', 'scale=640:480',
                '-c:v', 'libx264', '-preset', 'fast',
                '-crf', '28', '-c:a', 'aac', '-b:a', '64k',
                '-y', output_file
            ]
        else:
            # Compressão padrão
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
            # Verifica se o arquivo comprimido é menor que o alvo
            if os.path.getsize(output_file) <= target_size:
                return output_file
            else:
                os.remove(output_file)
                return None
        else:
            return None
            
    except Exception as e:
        logger.error(f"Erro na compressão: {e}")
        return None

async def send_video_part(chat_id, video_file, context, caption):
    """Envia uma parte do arquivo como vídeo, com fallback para documento."""
    try:
        filename = os.path.basename(video_file)
        
        # Tenta enviar como vídeo primeiro
        try:
            with open(video_file, 'rb') as video:
                await context.bot.send_video(
                    chat_id,
                    video=video,
                    caption=caption,
                    supports_streaming=True,
                    read_timeout=300,
                    write_timeout=300
                )
            logger.info(f"Parte enviada como vídeo: {filename}")
        except Exception as video_error:
            # Fallback para documento se envio como vídeo falhar
            logger.warning(f"Erro ao enviar como vídeo, tentando como documento: {video_error}")
            with open(video_file, 'rb') as file:
                await context.bot.send_document(
                    chat_id,
                    document=file,
                    filename=filename,
                    caption=caption,
                    read_timeout=300,
                    write_timeout=300
                )
            logger.info(f"Parte enviada como documento: {filename}")
            
    except Exception as e:
        logger.error(f"Erro ao enviar parte do arquivo: {e}")
        await context.bot.send_message(
            chat_id,
            f"❌ Erro ao enviar {caption}: {str(e)[:50]}..."
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
    """Divide arquivo em partes menores usando divisão binária simples."""
    try:
        file_size = os.path.getsize(video_file)
        if file_size <= max_size_bytes:
            return [video_file]
        
        # Calcula número de partes necessárias
        num_parts = (file_size + max_size_bytes - 1) // max_size_bytes
        
        parts = []
        base_name = os.path.splitext(video_file)[0]
        
        # Divisão binária simples (funciona para qualquer tipo de arquivo)
        with open(video_file, 'rb') as source:
            for i in range(num_parts):
                part_file = f"{base_name}_part{i+1}.mp4"
                
                # Calcula o tamanho desta parte
                start_pos = i * max_size_bytes
                remaining = file_size - start_pos
                part_size = min(max_size_bytes, remaining)
                
                # Lê e escreve a parte
                source.seek(start_pos)
                data = source.read(part_size)
                
                with open(part_file, 'wb') as part:
                    part.write(data)
                
                if os.path.exists(part_file) and os.path.getsize(part_file) > 0:
                    parts.append(part_file)
                    logger.info(f"Parte criada: {part_file} ({os.path.getsize(part_file)/1024/1024:.1f}MB)")
        
        return parts
        
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
    """Envia vídeo com fallback para documento em caso de timeout e compressão para arquivos grandes."""
    try:
        # Verifica o tamanho do arquivo (limite configurado: 40MB)
        file_size = os.path.getsize(video_file)
        max_size = 40 * 1024 * 1024  # 40MB em bytes conforme solicitado
        
        # Se o arquivo for muito grande, comprime
        if file_size > max_size:
            logger.info(f"Arquivo {video_file} muito grande ({file_size/1024/1024:.1f}MB), comprimindo...")
            compressed_file = await compress_video(video_file, max_size)
            if compressed_file and os.path.exists(compressed_file):
                video_file = compressed_file
                logger.info(f"Vídeo comprimido para {os.path.getsize(video_file)/1024/1024:.1f}MB")
            else:
                # Se a compressão falhar, tenta dividir o arquivo
                logger.warning("Compressão falhou, tentando dividir arquivo...")
                await context.bot.send_message(chat_id, "📹 Arquivo muito grande, dividindo em partes...")
                
                # Tenta dividir com FFmpeg primeiro (mantém formato de vídeo)
                parts = await split_video_with_ffmpeg(video_file, max_size)
                if not parts:
                    # Fallback para divisão binária se FFmpeg não estiver disponível
                    parts = await split_file_by_size(video_file, max_size)
                
                if parts:
                    for i, part in enumerate(parts, 1):
                        part_caption = f"{caption} - Parte {i}/{len(parts)}"
                        await send_video_part(chat_id, part, context, part_caption)
                        os.remove(part)  # Remove parte após envio
                    return
                else:
                    await context.bot.send_message(chat_id, "❌ Não foi possível processar o arquivo (muito grande)")
                    return
        
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
        elif "request entity too large" in str(video_error).lower() or "too large" in str(video_error).lower():
            logger.warning(f"Arquivo {video_file} muito grande para Telegram, tentando compressão adicional")
            await context.bot.send_message(chat_id, text=f"📹 Arquivo muito grande, tentando compressão adicional...")
            # Tenta compressão mais agressiva
            ultra_compressed = await compress_video(video_file, 30 * 1024 * 1024, aggressive=True)
            if ultra_compressed and os.path.exists(ultra_compressed):
                try:
                    with open(ultra_compressed, 'rb') as video:
                        await context.bot.send_video(
                            chat_id,
                            video=video,
                            caption=f"{caption} (Comprimido)",
                            read_timeout=300,
                            write_timeout=300
                        )
                    os.remove(ultra_compressed)
                    return
                except:
                    pass
            await context.bot.send_message(chat_id, "❌ Arquivo muito grande, não foi possível enviar")
            return
        else:
            logger.warning(f"Erro ao enviar {video_file} como vídeo: {video_error}")
        
        # Fallback para documento apenas se não for problema de tamanho
        if "too large" not in str(video_error).lower():
            try:
                with open(video_file, 'rb') as video:
                    await context.bot.send_document(
                        chat_id,
                        document=video,
                        filename=f"{caption.replace('/', '_')}.mp4",
                        read_timeout=300,
                        write_timeout=300
                    )
            except Exception as doc_error:
                logger.error(f"Erro ao enviar como documento: {doc_error}")
                await context.bot.send_message(chat_id, "❌ Não foi possível enviar o arquivo")

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