import logging
import os
import subprocess
import asyncio
import json
import glob
import time
from datetime import datetime
from PIL import Image
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.constants import ChatAction

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

# Configura o logging para debug
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Sistema de Fila de Downloads
download_queue = []  # Lista global para fila de downloads
queue_lock = asyncio.Lock()  # Lock para operações thread-safe
current_download = None  # Download atual em processamento
queue_file = 'download_queue.json'  # Arquivo para persistir a fila

# Estrutura de um item da fila
class QueueItem:
    def __init__(self, chat_id, url, download_type, user_name="Usuário", priority="normal"):
        self.id = f"{chat_id}_{int(datetime.now().timestamp())}"
        self.chat_id = chat_id
        self.url = url
        self.download_type = download_type  # 'video', 'images', 'audio'
        self.user_name = user_name
        self.priority = priority  # 'high', 'normal', 'low'
        self.status = 'pending'  # 'pending', 'downloading', 'completed', 'failed'
        self.added_time = datetime.now().isoformat()
        self.started_time = None
        self.completed_time = None
        self.error_message = None
        self.format_id = None  # Para qualidade específica
        self.video_index = None  # Para vídeo específico de playlist
    
    def to_dict(self):
        return {
            'id': self.id,
            'chat_id': self.chat_id,
            'url': self.url,
            'download_type': self.download_type,
            'user_name': self.user_name,
            'priority': self.priority,
            'status': self.status,
            'added_time': self.added_time,
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
        item.added_time = data['added_time']
        item.started_time = data['started_time']
        item.completed_time = data['completed_time']
        item.error_message = data['error_message']
        item.format_id = data.get('format_id')
        item.video_index = data.get('video_index')
        return item

# Função para carregar fila do arquivo
def load_queue():
    global download_queue
    try:
        if os.path.exists(queue_file):
            with open(queue_file, 'r', encoding='utf-8') as f:
                queue_data = json.load(f)
                download_queue = [QueueItem.from_dict(item) for item in queue_data]
                logger.info(f"Fila carregada com {len(download_queue)} itens")
    except Exception as e:
        logger.error(f"Erro ao carregar fila: {e}")
        download_queue = []

# Função para salvar fila no arquivo
def save_queue():
    try:
        with open(queue_file, 'w', encoding='utf-8') as f:
            queue_data = [item.to_dict() for item in download_queue]
            json.dump(queue_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Erro ao salvar fila: {e}")

# Função para adicionar item à fila
async def add_to_queue(chat_id, url, download_type, user_name="Usuário", priority="normal", format_id=None, video_index=None):
    async with queue_lock:
        item = QueueItem(chat_id, url, download_type, user_name, priority)
        item.format_id = format_id
        item.video_index = video_index
        
        # Insere baseado na prioridade
        if priority == 'high':
            download_queue.insert(0, item)
        else:
            download_queue.append(item)
        
        save_queue()
        logger.info(f"Item adicionado à fila: {item.id} - {download_type} - {url[:50]}...")
        return item

# Função para remover item da fila
async def remove_from_queue(item_id):
    async with queue_lock:
        global download_queue
        download_queue = [item for item in download_queue if item.id != item_id]
        save_queue()

# Função para obter próximo item da fila
async def get_next_queue_item():
    async with queue_lock:
        for item in download_queue:
            if item.status == 'pending':
                return item
        return None

# Função para verificar se fila está sendo processada
def is_queue_processing():
    return current_download is not None

# Função para limpar arquivos temporários
def cleanup_temp_files():
    """Remove arquivos temporários antigos (vídeos, imagens, etc.)."""
    try:
        current_time = time.time()
        files_removed = 0
        
        # Padrões de arquivos temporários
        patterns = [
            '*.mp4',
            '*.webm', 
            '*.mkv',
            '*.avi',
            '*.jpg',
            '*.jpeg',
            '*.png',
            '*.webp',
            '*.gif'
        ]
        
        for pattern in patterns:
            for file_path in glob.glob(pattern):
                try:
                    # Remove arquivos mais antigos que 1 hora
                    if current_time - os.path.getmtime(file_path) > 3600:
                        os.remove(file_path)
                        files_removed += 1
                        logger.info(f"Arquivo temporário removido: {file_path}")
                except Exception as e:
                    logger.warning(f"Erro ao remover arquivo {file_path}: {e}")
        
        if files_removed > 0:
            logger.info(f"Limpeza concluída: {files_removed} arquivos temporários removidos")
        
        return files_removed
        
    except Exception as e:
        logger.error(f"Erro na limpeza de arquivos temporários: {e}")
        return 0

# Função para limpeza forçada de todos os arquivos temporários
def force_cleanup_temp_files():
    """Remove todos os arquivos temporários, independente da idade."""
    try:
        files_removed = 0
        
        # Padrões de arquivos temporários
        patterns = [
            '*.mp4',
            '*.webm', 
            '*.mkv',
            '*.avi',
            '*.jpg',
            '*.jpeg',
            '*.png',
            '*.webp',
            '*.gif'
        ]
        
        for pattern in patterns:
            for file_path in glob.glob(pattern):
                try:
                    os.remove(file_path)
                    files_removed += 1
                    logger.info(f"Arquivo temporário removido: {file_path}")
                except Exception as e:
                    logger.warning(f"Erro ao remover arquivo {file_path}: {e}")
        
        logger.info(f"Limpeza forçada concluída: {files_removed} arquivos removidos")
        return files_removed
        
    except Exception as e:
        logger.error(f"Erro na limpeza forçada: {e}")
        return 0

# Função para verificar se ffmpeg está disponível
async def check_ffmpeg():
    """Verifica se ffmpeg está instalado no sistema."""
    try:
        process = await asyncio.create_subprocess_exec(
            'ffmpeg', '-version',
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        await process.communicate()
        return process.returncode == 0
    except:
        return False

# Função para dividir vídeo em partes menores usando yt-dlp
async def split_video_with_ytdlp(video_url, chat_id, message_id, max_size_bytes):
    """Baixa vídeo em partes usando yt-dlp com postprocessor."""
    try:
        # Calcula o tamanho aproximado de cada parte (em MB)
        max_size_mb = max_size_bytes // (1024 * 1024)
        
        # Comando yt-dlp para baixar em partes
        command = [
            'yt-dlp',
            '--postprocessor-args', f'ffmpeg:-fs {max_size_bytes}',
            '-f', 'best[height<=480]/worst',
            '--merge-output-format', 'mp4',
            '-o', f'{chat_id}_{message_id}_part%(autonumber)s.%(ext)s',
            video_url
        ]
        
        logger.info(f"Executando comando para partes: {' '.join(command)}")
        
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            # Procura pelos arquivos gerados
            video_parts = []
            for file in os.listdir('.'):
                if file.startswith(f"{chat_id}_{message_id}_part") and file.endswith('.mp4'):
                    video_parts.append(file)
            
            # Ordena as partes
            video_parts.sort()
            return video_parts if video_parts else None
        else:
            logger.error(f"Erro no yt-dlp para partes: {stderr.decode()}")
            return None
            
    except Exception as e:
        logger.error(f"Erro na função split_video_with_ytdlp: {e}")
        return None

# Função para verificar qualidade da imagem
def is_good_quality_image(image_path):
    """Verifica se a imagem tem qualidade suficiente para ser enviada."""
    try:
        # Verifica tamanho do arquivo (mínimo 5KB)
        file_size = os.path.getsize(image_path)
        if file_size < 5 * 1024:  # 5KB
            return False
        
        # Verifica resolução da imagem
        with Image.open(image_path) as img:
            width, height = img.size
            
            # Imagem muito pequena (menor que 100x100)
            if width < 100 or height < 100:
                return False
            
            # Imagem muito estreita ou muito alta (proporção ruim)
            aspect_ratio = max(width, height) / min(width, height)
            if aspect_ratio > 10:  # Muito desproporcional
                return False
            
            # Verifica se tem pixels suficientes (mínimo 10.000 pixels)
            total_pixels = width * height
            if total_pixels < 10000:
                return False
        
        return True
        
    except Exception as e:
        logger.warning(f"Erro ao verificar qualidade da imagem {image_path}: {e}")
        return False

# Função simples para dividir arquivo por tamanho (fallback)
async def split_file_by_size(video_file, max_size_bytes):
    """Divide arquivo binário em partes por tamanho (método simples)."""
    try:
        file_size = os.path.getsize(video_file)
        if file_size <= max_size_bytes:
            return [video_file]
        
        num_parts = (file_size // max_size_bytes) + 1
        base_name = os.path.splitext(video_file)[0]
        video_parts = []
        
        with open(video_file, 'rb') as input_file:
            for i in range(num_parts):
                part_file = f"{base_name}_part{i+1}.mp4"
                with open(part_file, 'wb') as output_file:
                    chunk = input_file.read(max_size_bytes)
                    if chunk:
                        output_file.write(chunk)
                        video_parts.append(part_file)
                    else:
                        break
        
        return video_parts
        
    except Exception as e:
        logger.error(f"Erro na função split_file_by_size: {e}")
        return None

# Função para o comando /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envia uma mensagem de boas-vindas quando o comando /start é emitido."""
    user = update.effective_user
    await update.message.reply_html(
        f"Olá, {user.mention_html()}!\n\n" +
        "🔗 **Envie qualquer link e escolha o que baixar:**\n" +
        "• 🎬 Vídeos (com divisão automática se necessário)\n" +
        "• 🖼️ Imagens (todas as disponíveis)\n\n" +
        "📋 Use /help para ver todos os comandos"
    )

# Função para o comando /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mostra a lista de comandos disponíveis."""
    help_text = (
        "🤖 **Como usar o bot:**\n\n"
        "🔗 **Modo principal (Recomendado):**\n"
        "• Envie qualquer link\n"
        "• Escolha entre 🎬 Vídeo ou 🖼️ Imagens\n"
        "• O bot processa automaticamente\n\n"
        "🎬 **Download de vídeos:**\n"
        "• Suporta YouTube, Instagram, TikTok, etc.\n"
        "• Vídeos grandes são divididos automaticamente\n"
        "• Enviados como vídeos reproduzíveis\n\n"
        "🖼️ **Download de imagens:**\n"
        "• Extrai todas as imagens disponíveis\n"
        "• Suporta JPG, PNG, WebP, GIF\n"
        "• Comando direto: `/images [URL]`\n\n"
        "📋 **Comandos:**\n"
        "• `/start` - Mensagem de boas-vindas\n"
        "• `/help` - Esta mensagem de ajuda\n"
        "• `/images [URL]` - Download direto de imagens\n"
        "• `/queue` - Ver fila de downloads\n"
        "• `/clear_queue` - Limpar fila de downloads\n"
        "• `/cut [URL] [início] [fim]` - Cortar vídeo por tempo\n"
        "• `/cleanup` - Limpar arquivos temporários\n"
        "• `/priority` - Adicionar download com prioridade alta"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

# Função para mostrar a fila de downloads
async def show_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mostra a fila de downloads atual."""
    chat_id = update.message.chat_id
    
    if not download_queue:
        await update.message.reply_text("📭 **Fila de downloads vazia**\n\nNenhum download na fila no momento.", parse_mode='Markdown')
        return
    
    # Filtra itens do usuário atual
    user_items = [item for item in download_queue if item.chat_id == chat_id]
    
    if not user_items:
        await update.message.reply_text("📭 **Sua fila está vazia**\n\nVocê não tem downloads na fila.", parse_mode='Markdown')
        return
    
    queue_text = "📋 **Sua Fila de Downloads:**\n\n"
    
    for i, item in enumerate(user_items[:10], 1):  # Mostra até 10 itens
        status_emoji = {
            'pending': '⏳',
            'downloading': '⬇️',
            'completed': '✅',
            'failed': '❌'
        }.get(item.status, '❓')
        
        priority_emoji = {
            'high': '🔥',
            'normal': '📺',
            'low': '🔽'
        }.get(item.priority, '📺')
        
        type_emoji = {
            'video': '🎬',
            'images': '🖼️',
            'audio': '🎵'
        }.get(item.download_type, '📁')
        
        url_short = item.url[:40] + "..." if len(item.url) > 40 else item.url
        
        queue_text += f"{i}. {status_emoji} {priority_emoji} {type_emoji} `{url_short}`\n"
        
        if item.status == 'failed' and item.error_message:
            queue_text += f"   ❌ Erro: {item.error_message[:50]}...\n"
    
    if len(user_items) > 10:
        queue_text += f"\n... e mais {len(user_items) - 10} itens\n"
    
    # Adiciona informações sobre processamento
    if current_download:
        queue_text += f"\n🔄 **Processando:** {current_download.download_type}\n"
    
    # Cria botões para gerenciar a fila
    keyboard = [
        [
            InlineKeyboardButton("🔄 Atualizar", callback_data="queue_refresh"),
            InlineKeyboardButton("🗑️ Limpar Concluídos", callback_data="queue_clear_completed")
        ],
        [
            InlineKeyboardButton("❌ Limpar Tudo", callback_data="queue_clear_all")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(queue_text, reply_markup=reply_markup, parse_mode='Markdown')

# Função para limpar a fila
async def clear_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Limpa a fila de downloads do usuário."""
    chat_id = update.message.chat_id
    
    async with queue_lock:
        global download_queue
        user_items_count = len([item for item in download_queue if item.chat_id == chat_id])
        download_queue = [item for item in download_queue if item.chat_id != chat_id]
        save_queue()
    
    if user_items_count > 0:
        await update.message.reply_text(f"🗑️ **Fila limpa!**\n\n{user_items_count} itens removidos da sua fila.", parse_mode='Markdown')
    else:
         await update.message.reply_text("📭 **Fila já estava vazia**\n\nNenhum item para remover.", parse_mode='Markdown')

# Função para limpar arquivos temporários via comando
async def cleanup_files(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Limpa arquivos temporários do servidor."""
    chat_id = update.message.chat_id
    
    await update.message.reply_text(
        "🧹 **Limpando arquivos temporários...**\n\n"
        "⏳ Aguarde um momento...",
        parse_mode='Markdown'
    )
    
    try:
        # Executa limpeza forçada
        files_removed = force_cleanup_temp_files()
        
        if files_removed > 0:
            await update.message.reply_text(
                f"✅ **Limpeza concluída!**\n\n"
                f"🗑️ {files_removed} arquivos temporários removidos\n"
                f"💾 Espaço em disco liberado",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "✅ **Limpeza concluída!**\n\n"
                "📁 Nenhum arquivo temporário encontrado\n"
                "🎉 Diretório já está limpo",
                parse_mode='Markdown'
            )
            
    except Exception as e:
        logger.error(f"Erro no comando de limpeza: {e}")
        await update.message.reply_text(
            f"❌ **Erro na limpeza**\n\n"
            f"Erro: {str(e)[:100]}...",
            parse_mode='Markdown'
        )

# Função para cortar vídeo por tempo
async def cut_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Corta vídeo por tempo específico (início/fim)."""
    chat_id = update.message.chat_id
    user_name = update.message.from_user.first_name or "Usuário"
    
    # Verifica se os argumentos foram fornecidos
    if len(context.args) < 3:
        await update.message.reply_text(
            "✂️ **Como usar o comando de corte:**\n\n"
            "📝 Formato: `/cut [URL] [início] [fim]`\n\n"
            "⏰ **Formatos de tempo aceitos:**\n"
            "• Segundos: `30` (30 segundos)\n"
            "• Minutos:segundos: `1:30` (1 min 30s)\n"
            "• Horas:minutos:segundos: `0:1:30`\n\n"
            "📌 **Exemplos:**\n"
            "• `/cut https://youtube.com/watch?v=abc 10 60`\n"
            "• `/cut https://youtube.com/watch?v=abc 1:30 3:45`\n"
            "• `/cut https://youtube.com/watch?v=abc 0:1:30 0:5:00`",
            parse_mode='Markdown'
        )
        return
    
    url = context.args[0]
    start_time = context.args[1]
    end_time = context.args[2]
    
    # Valida os tempos
    try:
        start_seconds = parse_time_to_seconds(start_time)
        end_seconds = parse_time_to_seconds(end_time)
        
        if start_seconds >= end_seconds:
            await update.message.reply_text(
                "❌ **Erro nos tempos!**\n\n"
                "O tempo de início deve ser menor que o tempo de fim.",
                parse_mode='Markdown'
            )
            return
        
        duration = end_seconds - start_seconds
        
        # Armazena URL no contexto para evitar callback_data longo
        if 'user_urls' not in context.user_data:
            context.user_data['user_urls'] = {}
        
        url_id = f"{chat_id}_{update.message.message_id}_cut"
        context.user_data['user_urls'][url_id] = url
        
        # Cria menu de opções para o corte
        keyboard = [
            [
                InlineKeyboardButton("✂️ Cortar Agora", callback_data=f"cut_now:{start_time}:{end_time}:{url_id}"),
                InlineKeyboardButton("📋 Adicionar à Fila", callback_data=f"cut_queue:{start_time}:{end_time}:{url_id}")
            ],
            [
                InlineKeyboardButton("🎬 Ver Qualidades", callback_data=f"cut_quality:{start_time}:{end_time}:{url_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"✂️ **Corte de vídeo configurado!**\n\n"
            f"🔗 **URL:** `{url[:50]}...`\n"
            f"⏰ **Início:** {start_time} ({start_seconds}s)\n"
            f"⏰ **Fim:** {end_time} ({end_seconds}s)\n"
            f"⏱️ **Duração:** {format_seconds_to_time(duration)}\n\n"
            f"Escolha uma opção:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except ValueError as e:
        await update.message.reply_text(
            f"❌ **Erro no formato de tempo!**\n\n"
            f"Erro: {str(e)}\n\n"
            f"Use formatos como: `30`, `1:30`, `0:1:30`",
            parse_mode='Markdown'
        )

# Função auxiliar para converter tempo em segundos
def parse_time_to_seconds(time_str):
    """Converte string de tempo para segundos."""
    try:
        # Se for apenas número (segundos)
        if ':' not in time_str:
            return int(time_str)
        
        # Se tiver formato mm:ss ou hh:mm:ss
        parts = time_str.split(':')
        if len(parts) == 2:  # mm:ss
            minutes, seconds = map(int, parts)
            return minutes * 60 + seconds
        elif len(parts) == 3:  # hh:mm:ss
            hours, minutes, seconds = map(int, parts)
            return hours * 3600 + minutes * 60 + seconds
        else:
            raise ValueError("Formato inválido")
    except ValueError:
        raise ValueError(f"Formato de tempo inválido: {time_str}")

# Função auxiliar para formatar segundos em tempo
def format_seconds_to_time(seconds):
    """Converte segundos para formato hh:mm:ss."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}"

# Função para executar corte de vídeo
async def execute_video_cut(chat_id, url, start_time, end_time, context, quality_format=None):
    """Executa o corte do vídeo."""
    try:
        await context.bot.send_message(chat_id, text="✂️ **Iniciando corte do vídeo...**")
        
        # Define o nome do arquivo de saída
        timestamp = int(datetime.now().timestamp())
        output_template = f"{chat_id}_{timestamp}_cut.%(ext)s"
        
        # Converte tempos para segundos
        start_seconds = parse_time_to_seconds(start_time)
        end_seconds = parse_time_to_seconds(end_time)
        duration = end_seconds - start_seconds
        
        # Comando yt-dlp com corte por tempo
        command = [
            'yt-dlp',
            '-f', quality_format or 'best[filesize<40M]/best[height<=480]/worst',
            '--merge-output-format', 'mp4',
            '--external-downloader', 'ffmpeg',
            '--external-downloader-args', f'ffmpeg:-ss {start_seconds} -t {duration}',
            '-o', output_template,
            url
        ]
        
        logger.info(f"Executando corte: {' '.join(command)}")
        
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            # Procura pelo arquivo cortado
            cut_file = None
            for file in os.listdir('.'):
                if file.startswith(f"{chat_id}_{timestamp}_cut") and file.endswith('.mp4'):
                    cut_file = file
                    break
            
            if cut_file:
                # Verifica tamanho e envia
                file_size = os.path.getsize(cut_file)
                max_size = 40 * 1024 * 1024  # 40MB
                
                if file_size > max_size:
                    await context.bot.send_message(
                        chat_id, 
                        text=f"📺 Vídeo cortado ({file_size / (1024*1024):.1f}MB). Dividindo..."
                    )
                    
                    # Divide o arquivo
                    video_parts = await split_file_by_size(cut_file, max_size)
                    
                    if video_parts and len(video_parts) > 1:
                        for i, part_file in enumerate(video_parts, 1):
                            await send_video_with_fallback(
                                chat_id, 
                                part_file, 
                                context, 
                                f"✂️ Corte {i}/{len(video_parts)} ({start_time}-{end_time})"
                            )
                            if part_file != cut_file:
                                os.remove(part_file)
                    else:
                        await send_video_with_fallback(
                            chat_id, 
                            cut_file, 
                            context, 
                            f"✂️ Vídeo cortado ({start_time}-{end_time})"
                        )
                else:
                    await send_video_with_fallback(
                        chat_id, 
                        cut_file, 
                        context, 
                        f"✂️ Vídeo cortado ({start_time}-{end_time})"
                    )
                
                # Remove arquivo original
                os.remove(cut_file)
                logger.info(f"Vídeo cortado enviado e removido: {cut_file}")
                
                await context.bot.send_message(
                    chat_id, 
                    text=f"✅ **Corte concluído!**\n\n"
                         f"⏰ Trecho: {start_time} - {end_time}\n"
                         f"⏱️ Duração: {format_seconds_to_time(duration)}",
                    parse_mode='Markdown'
                )
                return True
            else:
                await context.bot.send_message(chat_id, text="❌ Erro: arquivo cortado não encontrado.")
                return False
        else:
            error_message = stderr.decode('utf-8', errors='ignore')
            logger.error(f"Erro no corte de vídeo: {error_message}")
            await context.bot.send_message(
                chat_id, 
                text=f"❌ Erro ao cortar vídeo: {error_message.splitlines()[-1] if error_message.splitlines() else 'Erro desconhecido'}"
            )
            return False
    
    except Exception as e:
        logger.error(f"Erro no corte de vídeo: {e}")
        await context.bot.send_message(chat_id, text=f"❌ Erro ao cortar vídeo: {e}")
        return False

# Função para baixar imagens de uma URL
async def download_images(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Baixa todas as imagens de uma URL fornecida."""
    chat_id = update.message.chat_id
    
    # Verifica se foi fornecida uma URL
    if not context.args:
        await update.message.reply_text(
            "❌ Por favor, forneça uma URL após o comando.\n"
            "Exemplo: `/images https://example.com`",
            parse_mode='Markdown'
        )
        return
    
    url = context.args[0]
    
    # Avisa ao usuário que o processo começou
    await context.bot.send_message(chat_id, text=f"🔍 Procurando imagens em: {url}...")
    
    try:
        # Define o template de saída para imagens
        message_id = update.message.message_id
        output_template = f"{chat_id}_{message_id}_img%(autonumber)s.%(ext)s"
        
        # Comando yt-dlp para extrair imagens
        command = [
            'yt-dlp',
            '--write-thumbnail',
            '--write-all-thumbnails',
            '--skip-download',  # Não baixa vídeos, só imagens
            '-o', output_template,
            url
        ]
        
        logger.info(f"Executando comando para imagens: {' '.join(command)}")
        
        # Executa o comando de forma assíncrona
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            # Procura por arquivos de imagem baixados
            image_files = []
            for file in os.listdir('.'):
                if file.startswith(f"{chat_id}_{message_id}_img") and file.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif')):
                    image_files.append(file)
            
            if image_files:
                # Filtra imagens de boa qualidade
                good_quality_images = []
                low_quality_count = 0
                
                for image_file in image_files:
                    if is_good_quality_image(image_file):
                        good_quality_images.append(image_file)
                    else:
                        low_quality_count += 1
                        os.remove(image_file)  # Remove imagens de baixa qualidade
                        logger.info(f"Imagem de baixa qualidade removida: {image_file}")
                
                if good_quality_images:
                    quality_msg = f"📸 Encontradas {len(image_files)} imagens, enviando {len(good_quality_images)} de boa qualidade"
                    if low_quality_count > 0:
                        quality_msg += f" (filtradas {low_quality_count} de baixa qualidade)"
                    quality_msg += "..."
                    
                    await context.bot.send_message(chat_id, text=quality_msg)
                    
                    # Envia cada imagem de boa qualidade
                    for i, image_file in enumerate(good_quality_images, 1):
                        try:
                            with open(image_file, 'rb') as img_file:
                                await context.bot.send_photo(chat_id, photo=img_file, caption=f"Imagem {i}/{len(good_quality_images)}")
                            os.remove(image_file)
                            logger.info(f"Imagem {i} enviada e removida: {image_file}")
                        except Exception as img_error:
                            logger.error(f"Erro ao enviar imagem {image_file}: {img_error}")
                            # Remove o arquivo mesmo se der erro no envio
                            if os.path.exists(image_file):
                                os.remove(image_file)
                    
                    await context.bot.send_message(chat_id, text="✅ Todas as imagens de qualidade foram enviadas!")
                else:
                    await context.bot.send_message(chat_id, text=f"❌ Encontradas {len(image_files)} imagens, mas todas eram de baixa qualidade (muito pequenas ou ruins).")
            else:
                await context.bot.send_message(chat_id, text="❌ Nenhuma imagem encontrada nesta URL.")
        else:
            error_message = stderr.decode('utf-8', errors='ignore')
            logger.error(f"Erro no yt-dlp para imagens: {error_message}")
            await context.bot.send_message(chat_id, text=f"❌ Erro ao extrair imagens. Verifique se a URL é válida.\nErro: {error_message.splitlines()[-1] if error_message.splitlines() else 'Erro desconhecido'}")
    
    except Exception as e:
        logger.error(f"Erro inesperado no download de imagens: {e}")
        await context.bot.send_message(chat_id, text=f"❌ Ocorreu um erro inesperado: {e}")

# Função principal que lida com os links enviados
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mostra opções para o link enviado pelo usuário."""
    chat_id = update.message.chat_id
    message_text = update.message.text
    
    # Armazena a URL no contexto do usuário para evitar callback_data muito longo
    if 'user_urls' not in context.user_data:
        context.user_data['user_urls'] = {}
    
    # Cria um ID único para esta URL
    url_id = f"{chat_id}_{update.message.message_id}"
    context.user_data['user_urls'][url_id] = message_text
    
    # Cria botões inline com IDs curtos
    keyboard = [
        [
            InlineKeyboardButton("🎬 Baixar Vídeo", callback_data=f"video:{url_id}"),
            InlineKeyboardButton("🖼️ Baixar Imagens", callback_data=f"images:{url_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🔗 **Link detectado!**\n\n"
        f"📎 `{message_text}`\n\n"
        f"O que você gostaria de baixar?",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

# Função para processar arquivos de vídeo enviados diretamente
async def handle_video_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processa arquivos de vídeo enviados diretamente pelo usuário."""
    chat_id = update.message.chat_id
    video = update.message.video
    
    try:
        await update.message.reply_text(
            "🎬 **Vídeo recebido!**\n\n"
            "📹 Processando seu vídeo...\n"
            "⏳ Aguarde um momento...",
            parse_mode='Markdown'
        )
        
        # Baixa o arquivo de vídeo
        file = await context.bot.get_file(video.file_id)
        file_path = f"{chat_id}_{video.file_id}.mp4"
        await file.download_to_drive(file_path)
        
        # Verifica o tamanho do arquivo
        file_size = os.path.getsize(file_path)
        max_size = 50 * 1024 * 1024  # 50MB
        
        if file_size <= max_size:
            # Se o arquivo é pequeno o suficiente, reenvia diretamente
            with open(file_path, 'rb') as video_file:
                await context.bot.send_video(
                    chat_id,
                    video=video_file,
                    supports_streaming=True,
                    caption="✅ Vídeo processado com sucesso!",
                    read_timeout=300,
                    write_timeout=300
                )
        else:
            # Se o arquivo é muito grande, divide em partes
            await update.message.reply_text(
                "📦 **Vídeo muito grande!**\n\n"
                "🔄 Dividindo em partes menores...",
                parse_mode='Markdown'
            )
            
            video_parts = await split_file_by_size(file_path, max_size)
            
            if video_parts:
                await update.message.reply_text(
                    f"📤 **Enviando {len(video_parts)} partes...**",
                    parse_mode='Markdown'
                )
                
                for i, part_file in enumerate(video_parts, 1):
                    try:
                        with open(part_file, 'rb') as video_part:
                            await context.bot.send_video(
                                chat_id,
                                video=video_part,
                                supports_streaming=True,
                                caption=f"Parte {i}/{len(video_parts)}",
                                read_timeout=300,
                                write_timeout=300
                            )
                        os.remove(part_file)
                    except Exception as part_error:
                        logger.warning(f"Erro ao enviar parte {i}, enviando como documento: {part_error}")
                        with open(part_file, 'rb') as video_part:
                            await context.bot.send_document(
                                chat_id,
                                document=video_part,
                                filename=f"video_parte_{i}.mp4",
                                read_timeout=300,
                                write_timeout=300
                            )
                        os.remove(part_file)
                
                await update.message.reply_text(
                    "✅ **Vídeo processado e enviado em partes!**",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(
                    "❌ **Erro ao processar vídeo**\n\n"
                    "Não foi possível dividir o arquivo.",
                    parse_mode='Markdown'
                )
        
        # Remove o arquivo original
        if os.path.exists(file_path):
            os.remove(file_path)
            
    except Exception as e:
        logger.error(f"Erro ao processar vídeo: {e}")
        await update.message.reply_text(
            f"❌ **Erro ao processar vídeo**\n\n"
            f"Erro: {str(e)[:100]}...",
            parse_mode='Markdown'
        )
        
        # Remove arquivo em caso de erro
        if 'file_path' in locals() and os.path.exists(file_path):
            os.remove(file_path)

# Função para listar vídeos disponíveis
async def list_available_videos(url):
    """Lista todos os vídeos disponíveis em uma URL."""
    try:
        # Comando yt-dlp para listar vídeos sem baixar
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
            # Procura por múltiplos vídeos na saída
            if 'playlist' in output.lower() or len(output.split('\n')) > 20:
                return True  # Múltiplos vídeos encontrados
        
        return False  # Apenas um vídeo
        
    except Exception as e:
        logger.error(f"Erro ao listar vídeos: {e}")
        return False

# Função para obter qualidades de vídeo disponíveis
async def get_video_qualities(url):
    """Obtém as qualidades de vídeo disponíveis com tamanhos."""
    try:
        # Comando yt-dlp para listar formatos disponíveis
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
            qualities = []
            
            # Processa a saída para extrair informações de qualidade
            lines = output.split('\n')
            for line in lines:
                if 'mp4' in line and ('x' in line or 'p' in line):
                    parts = line.split()
                    if len(parts) >= 4:
                        format_id = parts[0]
                        
                        # Extrai resolução
                        resolution = 'Desconhecida'
                        for part in parts:
                            if 'x' in part and part.replace('x', '').replace('p', '').isdigit():
                                resolution = part
                                break
                            elif part.endswith('p') and part[:-1].isdigit():
                                resolution = part
                                break
                        
                        # Extrai tamanho do arquivo
                        size = 'Tamanho desconhecido'
                        for i, part in enumerate(parts):
                            if 'MiB' in part or 'GiB' in part or 'KiB' in part:
                                if i > 0:
                                    size = f"{parts[i-1]}{part}"
                                break
                            elif part.replace('.', '').replace('M', '').replace('G', '').replace('K', '').isdigit():
                                if 'M' in part or 'G' in part or 'K' in part:
                                    size = part + 'B'
                                    break
                        
                        # Determina a qualidade baseada na resolução
                        if '1080' in resolution:
                            quality_name = '🔥 Full HD (1080p)'
                        elif '720' in resolution:
                            quality_name = '⭐ HD (720p)'
                        elif '480' in resolution:
                            quality_name = '📺 SD (480p)'
                        elif '360' in resolution:
                            quality_name = '📱 Mobile (360p)'
                        elif '240' in resolution:
                            quality_name = '📞 Low (240p)'
                        else:
                            quality_name = f'📹 {resolution}'
                        
                        qualities.append({
                            'format_id': format_id,
                            'quality': quality_name,
                            'resolution': resolution,
                            'size': size
                        })
            
            # Remove duplicatas e ordena por qualidade (maior primeiro)
            unique_qualities = []
            seen_resolutions = set()
            
            # Ordena por resolução (maior primeiro)
            qualities.sort(key=lambda x: int(x['resolution'].replace('p', '').replace('x', '').split('x')[0] if 'x' in x['resolution'] else x['resolution'].replace('p', '') if x['resolution'].replace('p', '').isdigit() else '0'), reverse=True)
            
            for quality in qualities:
                if quality['resolution'] not in seen_resolutions:
                    unique_qualities.append(quality)
                    seen_resolutions.add(quality['resolution'])
                    
                    # Limita a 6 qualidades
                    if len(unique_qualities) >= 6:
                        break
            
            return unique_qualities
        
        return []
        
    except Exception as e:
        logger.error(f"Erro ao obter qualidades: {e}")
        return []

# Função para processar download de vídeo
async def download_video_from_callback(chat_id, message_text, context, callback_query):
    """Baixa o vídeo do link fornecido."""
    try:
        # Avisa ao usuário que o processo começou
        await context.bot.send_message(chat_id, text="🎬 Verificando vídeos disponíveis...")
        
        # Verifica se há múltiplos vídeos
        has_multiple_videos = await list_available_videos(message_text)
        
        if has_multiple_videos:
            # Armazena URL no contexto para evitar callback_data longo
            if 'user_urls' not in context.user_data:
                context.user_data['user_urls'] = {}
            
            url_id = f"{chat_id}_{callback_query.message.message_id}_multi"
            context.user_data['user_urls'][url_id] = message_text
            
            # Cria menu para escolher entre baixar um ou todos
            keyboard = [
                [
                    InlineKeyboardButton("📹 Baixar Primeiro Vídeo", callback_data=f"video_single:{url_id}"),
                    InlineKeyboardButton("📺 Baixar Todos os Vídeos", callback_data=f"video_all:{url_id}")
                ],
                [
                    InlineKeyboardButton("📋 Listar Vídeos Disponíveis", callback_data=f"video_list:{url_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id,
                text="🎬 **Múltiplos vídeos encontrados!**\n\n"
                     "Escolha uma opção:",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return
        
        # Se apenas um vídeo, adiciona à fila ou oferece opções
        user_name = callback_query.from_user.first_name or "Usuário"
        
        # Verifica se há múltiplas qualidades
        qualities = await get_video_qualities(message_text)
        
        if len(qualities) > 1:
            # Armazena URL no contexto para evitar callback_data longo
            if 'user_urls' not in context.user_data:
                context.user_data['user_urls'] = {}
            
            url_id = f"{chat_id}_{callback_query.message.message_id}_quality"
            context.user_data['user_urls'][url_id] = message_text
            
            # Cria menu para escolher qualidade
            keyboard = []
            
            for quality in qualities[:6]:  # Máximo 6 qualidades
                keyboard.append([
                    InlineKeyboardButton(
                        f"📺 {quality['quality']} - {quality['size']}", 
                        callback_data=f"quality:{quality['format_id']}:{url_id}"
                    )
                ])
            
            # Adiciona opções de fila
            keyboard.append([
                InlineKeyboardButton("⭐ Melhor Qualidade (Auto)", callback_data=f"quality:best:{url_id}"),
                InlineKeyboardButton("📋 Adicionar à Fila", callback_data=f"queue_add:video:{url_id}")
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id,
                text="📺 **Escolha a qualidade do vídeo:**\n\n"
                     "Selecione a qualidade desejada ou adicione à fila:",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return
        
        # Se apenas uma qualidade, adiciona à fila
        item = await add_to_queue(chat_id, message_text, 'video', user_name)
        await context.bot.send_message(
            chat_id, 
            text=f"📋 **Adicionado à fila!**\n\n"
                 f"🎬 Vídeo adicionado à fila de downloads\n"
                 f"📍 Posição na fila: {len([i for i in download_queue if i.status == 'pending'])}\n\n"
                 f"Use /queue para ver sua fila",
            parse_mode='Markdown'
        )
        
        # Inicia processamento da fila se não estiver rodando
        if not is_queue_processing():
            asyncio.create_task(process_download_queue(context))

        # Define o nome do arquivo de saída baseado no callback
        message_id = callback_query.message.message_id
        output_template = f"{chat_id}_{message_id}.%(ext)s"
        
        # Comando yt-dlp para baixar vídeo com limite de tamanho (40MB para margem de segurança)
        command = [
            'yt-dlp',
            '-f', 'best[filesize<40M]/best[height<=480]/worst',
            '--merge-output-format', 'mp4',
            '-o', output_template,
            message_text
        ]

        logger.info(f"Executando comando: {' '.join(command)}")
        
        # Executa o comando de forma assíncrona
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            # Encontra o nome do arquivo baixado
            downloaded_file = None
            for file in os.listdir('.'):
                if file.startswith(f"{chat_id}_{message_id}"):
                    downloaded_file = file
                    break
            
            if downloaded_file:
                logger.info(f"Download concluído: {downloaded_file}")
                
                # Verifica o tamanho do arquivo (limite do Telegram: 50MB)
                file_size = os.path.getsize(downloaded_file)
                max_size = 40 * 1024 * 1024  # 40MB em bytes para margem de segurança
                
                if file_size > max_size:
                    await context.bot.send_message(chat_id, text=f"Arquivo muito grande ({file_size / (1024*1024):.1f}MB). Dividindo em partes menores...")
                    
                    # Tenta dividir o arquivo em partes
                    video_parts = await split_file_by_size(downloaded_file, max_size)
                    
                    if video_parts and len(video_parts) > 1:
                        await context.bot.send_message(chat_id, text=f"Enviando {len(video_parts)} partes do arquivo...")
                        
                        for i, part_file in enumerate(video_parts, 1):
                             await context.bot.send_message(chat_id, text=f"Enviando parte {i}/{len(video_parts)}...")
                             try:
                                 with open(part_file, 'rb') as video_file:
                                     await context.bot.send_video(
                                         chat_id, 
                                         video=video_file, 
                                         supports_streaming=True, 
                                         caption=f"Parte {i}/{len(video_parts)}",
                                         read_timeout=300,
                                         write_timeout=300,
                                         connect_timeout=60
                                     )
                             except Exception as video_error:
                                 if "timed out" in str(video_error).lower() or "timeout" in str(video_error).lower():
                                     logger.warning(f"Timeout ao enviar parte {i} como vídeo, enviando como documento")
                                     await context.bot.send_message(chat_id, text=f"⏰ Timeout na parte {i}, enviando como documento...")
                                 else:
                                     logger.warning(f"Erro ao enviar como vídeo, enviando como documento: {video_error}")
                                 
                                 with open(part_file, 'rb') as video_file:
                                     await context.bot.send_document(
                                         chat_id, 
                                         document=video_file, 
                                         filename=f"video_parte_{i}.mp4",
                                         read_timeout=300,
                                         write_timeout=300
                                     )
                             if part_file != downloaded_file:  # Não remove o arquivo original se for o mesmo
                                 os.remove(part_file)
                             logger.info(f"Parte {i} enviada e removida: {part_file}")
                    else:
                         await context.bot.send_message(chat_id, text="Erro ao dividir o arquivo. Tentando enviar como vídeo...")
                         # Tenta enviar como vídeo primeiro, depois como documento
                         try:
                             with open(downloaded_file, 'rb') as video_file:
                                 await context.bot.send_video(
                                     chat_id, 
                                     video=video_file, 
                                     supports_streaming=True,
                                     read_timeout=300,
                                     write_timeout=300,
                                     connect_timeout=60
                                 )
                         except Exception as video_error:
                             if "timed out" in str(video_error).lower() or "timeout" in str(video_error).lower():
                                 logger.warning(f"Timeout ao enviar vídeo, enviando como documento")
                                 await context.bot.send_message(chat_id, text="⏰ Timeout ao enviar vídeo. Enviando como documento...")
                             else:
                                 logger.warning(f"Erro ao enviar como vídeo, enviando como documento: {video_error}")
                                 await context.bot.send_message(chat_id, text="Enviando como documento...")
                             
                             with open(downloaded_file, 'rb') as video_file:
                                 await context.bot.send_document(
                                     chat_id, 
                                     document=video_file, 
                                     filename="video.mp4",
                                     read_timeout=300,
                                     write_timeout=300
                                 )
                    
                    # Remove o arquivo original
                    os.remove(downloaded_file)
                    logger.info(f"Arquivo original removido: {downloaded_file}")
                else:
                    await context.bot.send_message(chat_id, text="Download finalizado! Enviando o vídeo...")
                    
                    # Envia o vídeo com timeout estendido
                    try:
                        with open(downloaded_file, 'rb') as video_file:
                            await context.bot.send_video(
                                chat_id, 
                                video=video_file, 
                                supports_streaming=True,
                                read_timeout=300,  # 5 minutos
                                write_timeout=300,  # 5 minutos
                                connect_timeout=60  # 1 minuto
                            )
                    except Exception as send_error:
                        if "timed out" in str(send_error).lower() or "timeout" in str(send_error).lower():
                            await context.bot.send_message(chat_id, text="⏰ Timeout ao enviar vídeo. Tentando enviar como documento...")
                            try:
                                with open(downloaded_file, 'rb') as video_file:
                                    await context.bot.send_document(
                                        chat_id, 
                                        document=video_file, 
                                        filename="video.mp4",
                                        read_timeout=300,
                                        write_timeout=300
                                    )
                            except Exception as doc_error:
                                await context.bot.send_message(chat_id, text=f"❌ Erro ao enviar arquivo: {str(doc_error)[:100]}...")
                        else:
                            raise send_error
                    
                    # Apaga o arquivo do servidor para economizar espaço
                    os.remove(downloaded_file)
                    logger.info(f"Arquivo removido: {downloaded_file}")
            else:
                await context.bot.send_message(chat_id, text="Erro: não foi possível encontrar o arquivo baixado.")
        else:
            # Se der erro, informa o usuário e loga o erro
            error_message = stderr.decode('utf-8', errors='ignore')
            logger.error(f"Erro no yt-dlp: {error_message}")
            await context.bot.send_message(chat_id, text=f"Desculpe, não consegui baixar o vídeo. Verifique o link ou tente um diferente.\nErro: {error_message.splitlines()[-1]}")

    except Exception as e:
        logger.error(f"Ocorreu um erro inesperado: {e}")
        await context.bot.send_message(chat_id, text=f"Ocorreu um erro inesperado: {e}")

# Função para processar download de imagens via callback
async def download_images_from_callback(chat_id, message_text, context, callback_query):
    """Baixa imagens do link fornecido."""
    try:
        # Avisa ao usuário que o processo começou
        await context.bot.send_message(chat_id, text=f"🖼️ Procurando imagens em: {message_text}...")
        
        # Define o template de saída para imagens
        message_id = callback_query.message.message_id
        output_template = f"{chat_id}_{message_id}_img%(autonumber)s.%(ext)s"
        
        # Comando yt-dlp para extrair imagens
        command = [
            'yt-dlp',
            '--write-thumbnail',
            '--write-all-thumbnails',
            '--skip-download',  # Não baixa vídeos, só imagens
            '-o', output_template,
            message_text
        ]
        
        logger.info(f"Executando comando para imagens: {' '.join(command)}")
        
        # Executa o comando de forma assíncrona
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            # Procura por arquivos de imagem baixados
            image_files = []
            for file in os.listdir('.'):
                if file.startswith(f"{chat_id}_{message_id}_img") and file.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif')):
                    image_files.append(file)
            
            if image_files:
                 # Filtra imagens de boa qualidade
                 good_quality_images = []
                 low_quality_count = 0
                 
                 for image_file in image_files:
                     if is_good_quality_image(image_file):
                         good_quality_images.append(image_file)
                     else:
                         low_quality_count += 1
                         os.remove(image_file)  # Remove imagens de baixa qualidade
                         logger.info(f"Imagem de baixa qualidade removida: {image_file}")
                 
                 if good_quality_images:
                     quality_msg = f"📸 Encontradas {len(image_files)} imagens, enviando {len(good_quality_images)} de boa qualidade"
                     if low_quality_count > 0:
                         quality_msg += f" (filtradas {low_quality_count} de baixa qualidade)"
                     quality_msg += "..."
                     
                     await context.bot.send_message(chat_id, text=quality_msg)
                     
                     # Envia cada imagem de boa qualidade
                     for i, image_file in enumerate(good_quality_images, 1):
                         try:
                             with open(image_file, 'rb') as img_file:
                                 await context.bot.send_photo(chat_id, photo=img_file, caption=f"Imagem {i}/{len(good_quality_images)}")
                             os.remove(image_file)
                             logger.info(f"Imagem {i} enviada e removida: {image_file}")
                         except Exception as img_error:
                             logger.error(f"Erro ao enviar imagem {image_file}: {img_error}")
                             # Remove o arquivo mesmo se der erro no envio
                             if os.path.exists(image_file):
                                 os.remove(image_file)
                     
                     await context.bot.send_message(chat_id, text="✅ Todas as imagens de qualidade foram enviadas!")
                 else:
                     await context.bot.send_message(chat_id, text=f"❌ Encontradas {len(image_files)} imagens, mas todas eram de baixa qualidade (muito pequenas ou ruins).")
            else:
                await context.bot.send_message(chat_id, text="❌ Nenhuma imagem encontrada nesta URL.")
        else:
            error_message = stderr.decode('utf-8', errors='ignore')
            logger.error(f"Erro no yt-dlp para imagens: {error_message}")
            await context.bot.send_message(chat_id, text=f"❌ Erro ao extrair imagens. Verifique se a URL é válida.\nErro: {error_message.splitlines()[-1] if error_message.splitlines() else 'Erro desconhecido'}")
    
    except Exception as e:
        logger.error(f"Erro inesperado no download de imagens: {e}")
        await context.bot.send_message(chat_id, text=f"❌ Ocorreu um erro inesperado: {e}")

# Função para baixar vídeo único
async def download_single_video(chat_id, url, context, callback_query):
    """Baixa apenas o primeiro vídeo de uma playlist."""
    try:
        await context.bot.send_message(chat_id, text="📹 Baixando primeiro vídeo...")
        
        # Define o nome do arquivo de saída
        message_id = callback_query.message.message_id
        output_template = f"{chat_id}_{message_id}.%(ext)s"
        
        # Comando yt-dlp para baixar apenas o primeiro vídeo
        command = [
            'yt-dlp',
            '-f', 'best[filesize<40M]/best[height<=480]/worst',
            '--merge-output-format', 'mp4',
            '--playlist-items', '1',  # Apenas o primeiro item
            '-o', output_template,
            url
        ]
        
        # Executa o download do vídeo único
        logger.info(f"Executando comando para vídeo único: {' '.join(command)}")
        
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            # Procura pelo arquivo baixado
            downloaded_file = None
            for file in os.listdir('.'):
                if file.startswith(f"{chat_id}_{message_id}") and file.endswith('.mp4'):
                    downloaded_file = file
                    break
            
            if downloaded_file:
                await send_video_with_fallback(chat_id, downloaded_file, context, "Primeiro vídeo")
                os.remove(downloaded_file)
                logger.info(f"Vídeo único enviado e removido: {downloaded_file}")
                await context.bot.send_message(chat_id, text="✅ Primeiro vídeo enviado!")
            else:
                await context.bot.send_message(chat_id, text="❌ Erro: arquivo não encontrado.")
        else:
            error_message = stderr.decode('utf-8', errors='ignore')
            logger.error(f"Erro no yt-dlp para vídeo único: {error_message}")
            await context.bot.send_message(chat_id, text=f"❌ Erro ao baixar vídeo: {error_message.splitlines()[-1] if error_message.splitlines() else 'Erro desconhecido'}")
        
    except Exception as e:
        logger.error(f"Erro no download de vídeo único: {e}")
        await context.bot.send_message(chat_id, text=f"❌ Erro ao baixar vídeo: {e}")

# Função para baixar todos os vídeos
async def download_all_videos(chat_id, url, context, callback_query):
    """Baixa todos os vídeos de uma playlist."""
    try:
        await context.bot.send_message(chat_id, text="📺 Baixando todos os vídeos...")
        
        # Define o nome do arquivo de saída
        message_id = callback_query.message.message_id
        output_template = f"{chat_id}_{message_id}_%(playlist_index)s.%(ext)s"
        
        # Comando yt-dlp para baixar todos os vídeos
        command = [
            'yt-dlp',
            '-f', 'best[filesize<40M]/best[height<=480]/worst',
            '--merge-output-format', 'mp4',
            '-o', output_template,
            url
        ]
        
        logger.info(f"Executando comando para todos os vídeos: {' '.join(command)}")
        
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            # Procura por todos os arquivos baixados
            video_files = []
            for file in os.listdir('.'):
                if file.startswith(f"{chat_id}_{message_id}_") and file.endswith('.mp4'):
                    video_files.append(file)
            
            video_files.sort()  # Ordena por nome
            
            if video_files:
                await context.bot.send_message(chat_id, text=f"📺 {len(video_files)} vídeos baixados! Enviando...")
                
                for i, video_file in enumerate(video_files, 1):
                    await send_video_with_fallback(chat_id, video_file, context, f"Vídeo {i}/{len(video_files)}")
                    os.remove(video_file)
                    logger.info(f"Vídeo {i} enviado e removido: {video_file}")
                
                await context.bot.send_message(chat_id, text="✅ Todos os vídeos foram enviados!")
            else:
                await context.bot.send_message(chat_id, text="❌ Nenhum vídeo foi baixado.")
        else:
            error_message = stderr.decode('utf-8', errors='ignore')
            logger.error(f"Erro no yt-dlp para todos os vídeos: {error_message}")
            await context.bot.send_message(chat_id, text=f"❌ Erro ao baixar vídeos: {error_message.splitlines()[-1] if error_message.splitlines() else 'Erro desconhecido'}")
    
    except Exception as e:
        logger.error(f"Erro no download de todos os vídeos: {e}")
        await context.bot.send_message(chat_id, text=f"❌ Erro ao baixar vídeos: {e}")

# Função auxiliar para enviar vídeo com fallback
async def send_video_with_fallback(chat_id, video_file, context, caption=""):
    """Envia vídeo com fallback para documento em caso de timeout."""
    try:
        with open(video_file, 'rb') as video:
            await context.bot.send_video(
                chat_id,
                video=video,
                supports_streaming=True,
                caption=caption,
                read_timeout=300,
                write_timeout=300,
                connect_timeout=60
            )
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

# Função para listar vídeos detalhadamente
async def list_videos_detailed(chat_id, url, context):
    """Lista todos os vídeos disponíveis com detalhes."""
    try:
        await context.bot.send_message(chat_id, text="📋 Obtendo lista de vídeos...")
        
        # Comando yt-dlp para obter informações dos vídeos
        command = [
            'yt-dlp',
            '--get-title',
            '--get-duration',
            '--get-id',
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
            output_lines = stdout.decode('utf-8', errors='ignore').strip().split('\n')
            
            if len(output_lines) >= 3:
                # Agrupa as informações (título, duração, ID)
                videos_info = []
                for i in range(0, len(output_lines), 3):
                    if i + 2 < len(output_lines):
                        title = output_lines[i][:50] + "..." if len(output_lines[i]) > 50 else output_lines[i]
                        duration = output_lines[i + 1] if output_lines[i + 1] != 'NA' else "Duração desconhecida"
                        video_id = output_lines[i + 2]
                        videos_info.append(f"🎬 **{title}**\n⏱️ {duration}\n🆔 `{video_id}`")
                
                if videos_info:
                     # Limita a 8 vídeos para não sobrecarregar os botões
                     videos_to_show = videos_info[:8]
                     
                     video_list = "\n\n".join(videos_to_show)
                     
                     if len(videos_info) > 8:
                         video_list += f"\n\n... e mais {len(videos_info) - 8} vídeos"
                     
                     # Cria botões individuais para cada vídeo (máximo 8)
                     keyboard = []
                     
                     # Adiciona botões para vídeos individuais
                     for i in range(min(len(videos_info), 8)):
                         # Extrai o título do vídeo (primeiras 25 caracteres)
                         title_lines = videos_info[i].split('\n')
                         title = title_lines[0].replace('🎬 **', '').replace('**', '')
                         short_title = title[:25] + "..." if len(title) > 25 else title
                         
                         keyboard.append([
                             InlineKeyboardButton(
                                 f"📹 {i+1}. {short_title}", 
                                 callback_data=f"video_index:{i+1}:{url}"
                             )
                         ])
                     
                     # Adiciona botões de ação geral
                     keyboard.append([
                         InlineKeyboardButton("📺 Baixar Todos", callback_data=f"video_all:{url}"),
                         InlineKeyboardButton("🔄 Atualizar Lista", callback_data=f"video_list:{url}")
                     ])
                     
                     reply_markup = InlineKeyboardMarkup(keyboard)
                     
                     await context.bot.send_message(
                         chat_id,
                         text=f"📋 **Escolha o vídeo para baixar:**\n\n{video_list}",
                         reply_markup=reply_markup,
                         parse_mode='Markdown'
                     )
                else:
                    await context.bot.send_message(chat_id, text="❌ Não foi possível obter informações dos vídeos.")
            else:
                await context.bot.send_message(chat_id, text="📹 Apenas um vídeo encontrado. Use a opção de download normal.")
        else:
            error_message = stderr.decode('utf-8', errors='ignore')
            logger.error(f"Erro ao listar vídeos: {error_message}")
            await context.bot.send_message(chat_id, text="❌ Erro ao obter lista de vídeos.")
    
    except Exception as e:
        logger.error(f"Erro na listagem detalhada: {e}")
        await context.bot.send_message(chat_id, text=f"❌ Erro ao listar vídeos: {e}")

# Função para baixar vídeo por índice específico
async def download_video_by_index(chat_id, url, video_index, context, callback_query):
    """Baixa um vídeo específico pelo seu índice na playlist."""
    try:
        await context.bot.send_message(chat_id, text=f"📹 Baixando vídeo #{video_index}...")
        
        # Define o nome do arquivo de saída
        message_id = callback_query.message.message_id
        output_template = f"{chat_id}_{message_id}_video{video_index}.%(ext)s"
        
        # Comando yt-dlp para baixar vídeo específico pelo índice
        command = [
            'yt-dlp',
            '-f', 'best[filesize<40M]/best[height<=480]/worst',
            '--merge-output-format', 'mp4',
            '--playlist-items', str(video_index),  # Baixa apenas o vídeo do índice especificado
            '-o', output_template,
            url
        ]
        
        logger.info(f"Executando comando para vídeo #{video_index}: {' '.join(command)}")
        
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            # Procura pelo arquivo baixado
            downloaded_file = None
            for file in os.listdir('.'):
                if file.startswith(f"{chat_id}_{message_id}_video{video_index}") and file.endswith('.mp4'):
                    downloaded_file = file
                    break
            
            if downloaded_file:
                await send_video_with_fallback(chat_id, downloaded_file, context, f"Vídeo #{video_index}")
                os.remove(downloaded_file)
                logger.info(f"Vídeo #{video_index} enviado e removido: {downloaded_file}")
                await context.bot.send_message(chat_id, text=f"✅ Vídeo #{video_index} enviado com sucesso!")
            else:
                await context.bot.send_message(chat_id, text=f"❌ Erro: vídeo #{video_index} não encontrado após download.")
        else:
            error_message = stderr.decode('utf-8', errors='ignore')
            logger.error(f"Erro no yt-dlp para vídeo #{video_index}: {error_message}")
            await context.bot.send_message(chat_id, text=f"❌ Erro ao baixar vídeo #{video_index}: {error_message.splitlines()[-1] if error_message.splitlines() else 'Erro desconhecido'}")
    
    except Exception as e:
        logger.error(f"Erro no download do vídeo #{video_index}: {e}")
        await context.bot.send_message(chat_id, text=f"❌ Erro ao baixar vídeo #{video_index}: {e}")

# Função para baixar vídeo com qualidade específica
async def download_video_with_quality(chat_id, url, format_id, context, callback_query):
    """Baixa vídeo com qualidade específica."""
    try:
        if format_id == 'best':
            await context.bot.send_message(chat_id, text="⭐ Baixando na melhor qualidade disponível...")
            format_selector = 'best[filesize<40M]/best[height<=480]/worst'
        else:
            await context.bot.send_message(chat_id, text=f"📺 Baixando na qualidade selecionada...")
            format_selector = f'{format_id}+bestaudio/best[format_id={format_id}]/{format_id}'
        
        # Define o nome do arquivo de saída
        message_id = callback_query.message.message_id
        output_template = f"{chat_id}_{message_id}_quality.%(ext)s"
        
        # Comando yt-dlp para baixar com qualidade específica
        command = [
            'yt-dlp',
            '-f', format_selector,
            '--merge-output-format', 'mp4',
            '-o', output_template,
            url
        ]
        
        logger.info(f"Executando comando para qualidade {format_id}: {' '.join(command)}")
        
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            # Procura pelo arquivo baixado
            downloaded_file = None
            for file in os.listdir('.'):
                if file.startswith(f"{chat_id}_{message_id}_quality") and file.endswith('.mp4'):
                    downloaded_file = file
                    break
            
            if downloaded_file:
                # Verifica o tamanho do arquivo
                file_size = os.path.getsize(downloaded_file)
                max_size = 40 * 1024 * 1024  # 40MB
                
                if file_size > max_size:
                    await context.bot.send_message(chat_id, text=f"📺 Arquivo grande ({file_size / (1024*1024):.1f}MB). Dividindo...")
                    
                    # Divide o arquivo em partes
                    video_parts = await split_file_by_size(downloaded_file, max_size)
                    
                    if video_parts and len(video_parts) > 1:
                        await context.bot.send_message(chat_id, text=f"📺 Enviando {len(video_parts)} partes...")
                        
                        for i, part_file in enumerate(video_parts, 1):
                            await send_video_with_fallback(chat_id, part_file, context, f"Parte {i}/{len(video_parts)}")
                            if part_file != downloaded_file:
                                os.remove(part_file)
                            logger.info(f"Parte {i} enviada: {part_file}")
                    else:
                        await send_video_with_fallback(chat_id, downloaded_file, context, "Vídeo na qualidade selecionada")
                    
                    os.remove(downloaded_file)
                else:
                    await send_video_with_fallback(chat_id, downloaded_file, context, "Vídeo na qualidade selecionada")
                    os.remove(downloaded_file)
                
                logger.info(f"Vídeo com qualidade {format_id} enviado e removido: {downloaded_file}")
                await context.bot.send_message(chat_id, text="✅ Vídeo enviado na qualidade selecionada!")
            else:
                await context.bot.send_message(chat_id, text="❌ Erro: arquivo não encontrado após download.")
        else:
            error_message = stderr.decode('utf-8', errors='ignore')
            logger.error(f"Erro no yt-dlp para qualidade {format_id}: {error_message}")
            await context.bot.send_message(chat_id, text=f"❌ Erro ao baixar na qualidade selecionada: {error_message.splitlines()[-1] if error_message.splitlines() else 'Erro desconhecido'}")
    
    except Exception as e:
        logger.error(f"Erro no download com qualidade {format_id}: {e}")
        await context.bot.send_message(chat_id, text=f"❌ Erro ao baixar vídeo: {e}")

# Processador da fila de downloads
async def process_download_queue(context):
    """Processa a fila de downloads sequencialmente."""
    global current_download
    
    while True:
        try:
            # Obtém próximo item da fila
            item = await get_next_queue_item()
            
            if not item:
                # Fila vazia, para o processamento
                current_download = None
                logger.info("Fila de downloads vazia, parando processamento")
                break
            
            # Marca item como sendo processado
            current_download = item
            item.status = 'downloading'
            item.started_time = datetime.now().isoformat()
            save_queue()
            
            logger.info(f"Processando item da fila: {item.id} - {item.download_type}")
            
            # Notifica usuário que download começou
            type_emojis = {'video': '🎬', 'images': '🖼️', 'audio': '🎵'}
            type_emoji = type_emojis.get(item.download_type, '📁')
            
            await context.bot.send_message(
                item.chat_id,
                text=f"⬇️ **Download iniciado!**\n\n"
                     f"{type_emoji} {item.download_type.title()}\n"
                     f"📎 `{item.url[:50]}...`",
                parse_mode='Markdown'
            )
            
            # Executa o download baseado no tipo
            success = False
            try:
                if item.download_type == 'video':
                    if item.format_id:
                        # Download com qualidade específica
                        success = await execute_quality_download(item, context)
                    elif item.video_index:
                        # Download de vídeo específico da playlist
                        success = await execute_index_download(item, context)
                    else:
                        # Download normal de vídeo
                        success = await execute_video_download(item, context)
                elif item.download_type == 'images':
                    success = await execute_images_download(item, context)
                elif item.download_type == 'video_cut':
                    success = await execute_video_cut_from_queue(item, context)
                
                if success:
                    item.status = 'completed'
                    item.completed_time = datetime.now().isoformat()
                    type_emojis = {'video': '🎬', 'images': '🖼️', 'audio': '🎵'}
                    type_emoji = type_emojis.get(item.download_type, '📁')
                    
                    await context.bot.send_message(
                        item.chat_id,
                        text=f"✅ **Download concluído!**\n\n"
                             f"{type_emoji} {item.download_type.title()} enviado com sucesso!",
                        parse_mode='Markdown'
                    )
                else:
                    item.status = 'failed'
                    item.error_message = "Falha no download"
                    await context.bot.send_message(
                        item.chat_id,
                        text=f"❌ **Download falhou!**\n\n"
                             f"Erro ao processar {item.download_type}",
                        parse_mode='Markdown'
                    )
            
            except Exception as e:
                item.status = 'failed'
                item.error_message = str(e)[:100]
                logger.error(f"Erro no processamento da fila: {e}")
                await context.bot.send_message(
                    item.chat_id,
                    text=f"❌ **Erro no download!**\n\n"
                         f"Erro: {str(e)[:50]}...",
                    parse_mode='Markdown'
                )
            
            finally:
                save_queue()
                # Pequena pausa entre downloads
                await asyncio.sleep(2)
        
        except Exception as e:
            logger.error(f"Erro crítico no processador de fila: {e}")
            current_download = None
            break
    
    # Executa limpeza automática ao finalizar processamento da fila
    try:
        cleanup_temp_files()
    except Exception as e:
        logger.warning(f"Erro na limpeza automática: {e}")
    
    current_download = None

# Função auxiliar para executar download de vídeo da fila
async def execute_video_download(item, context):
    """Executa download de vídeo normal da fila."""
    try:
        # Implementa lógica similar ao download_video_from_callback
        # mas adaptada para trabalhar com QueueItem
        return True  # Placeholder - implementar lógica completa
    except Exception as e:
        logger.error(f"Erro no download de vídeo da fila: {e}")
        return False

# Função auxiliar para executar download de imagens da fila
async def execute_images_download(item, context):
    """Executa download de imagens da fila."""
    try:
        # Implementa lógica similar ao download_images_from_callback
        # mas adaptada para trabalhar com QueueItem
        return True  # Placeholder - implementar lógica completa
    except Exception as e:
        logger.error(f"Erro no download de imagens da fila: {e}")
        return False

# Função auxiliar para executar download com qualidade específica da fila
async def execute_quality_download(item, context):
    """Executa download com qualidade específica da fila."""
    try:
        # Implementa lógica similar ao download_video_with_quality
        # mas adaptada para trabalhar com QueueItem
        return True  # Placeholder - implementar lógica completa
    except Exception as e:
        logger.error(f"Erro no download com qualidade da fila: {e}")
        return False

# Função auxiliar para executar download por índice da fila
async def execute_index_download(item, context):
    """Executa download por índice da fila."""
    try:
        # Implementa lógica similar ao download_video_by_index
        # mas adaptada para trabalhar com QueueItem
        return True  # Placeholder - implementar lógica completa
    except Exception as e:
        logger.error(f"Erro no download por índice da fila: {e}")
        return False

# Função auxiliar para executar corte de vídeo da fila
async def execute_video_cut_from_queue(item, context):
    """Executa corte de vídeo da fila."""
    try:
        # Extrai tempos do format_id
        if item.format_id and ':' in item.format_id:
            start_time, end_time = item.format_id.split(':', 1)
            return await execute_video_cut(item.chat_id, item.url, start_time, end_time, context)
        else:
            logger.error(f"Formato de tempo inválido no item da fila: {item.format_id}")
            return False
    except Exception as e:
        logger.error(f"Erro no corte de vídeo da fila: {e}")
        return False
    
# Função para lidar com callbacks dos botões inline
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processa os callbacks dos botões inline."""
    query = update.callback_query
    await query.answer()
    
    # Extrai o tipo de ação e os dados do callback_data
    callback_parts = query.data.split(':', 2)
    action = callback_parts[0]
    chat_id = query.message.chat_id
    
    # Recupera a URL do contexto do usuário
    def get_url_from_context(url_id):
        if 'user_urls' in context.user_data and url_id in context.user_data['user_urls']:
            return context.user_data['user_urls'][url_id]
        return url_id  # Fallback para compatibilidade com URLs antigas
    
    # Edita a mensagem para mostrar a escolha
    if action == 'video':
        url_id = callback_parts[1]
        url = get_url_from_context(url_id)
        await query.edit_message_text(f"🎬 **Baixando vídeo...**\n\n📎 `{url}`", parse_mode='Markdown')
        await download_video_from_callback(chat_id, url, context, query)
    elif action == 'video_single':
        url_id = callback_parts[1]
        url = get_url_from_context(url_id)
        await query.edit_message_text(f"📹 **Baixando primeiro vídeo...**\n\n📎 `{url}`", parse_mode='Markdown')
        await download_single_video(chat_id, url, context, query)
    elif action == 'video_all':
        url_id = callback_parts[1]
        url = get_url_from_context(url_id)
        await query.edit_message_text(f"📺 **Baixando todos os vídeos...**\n\n📎 `{url}`", parse_mode='Markdown')
        await download_all_videos(chat_id, url, context, query)
    elif action == 'video_index':
        video_index = callback_parts[1]
        url_id = callback_parts[2]
        url = get_url_from_context(url_id)
        await query.edit_message_text(f"📹 **Baixando vídeo #{video_index}...**\n\n📎 `{url}`", parse_mode='Markdown')
        await download_video_by_index(chat_id, url, int(video_index), context, query)
    elif action == 'video_list':
        url_id = callback_parts[1]
        url = get_url_from_context(url_id)
        await query.edit_message_text(f"📋 **Listando vídeos disponíveis...**\n\n📎 `{url}`", parse_mode='Markdown')
        await list_videos_detailed(chat_id, url, context)
    elif action == 'quality':
        format_id = callback_parts[1]
        url_id = callback_parts[2]
        url = get_url_from_context(url_id)
        if format_id == 'best':
            await query.edit_message_text(f"⭐ **Baixando melhor qualidade...**\n\n📎 `{url}`", parse_mode='Markdown')
        else:
            await query.edit_message_text(f"📺 **Baixando qualidade selecionada...**\n\n📎 `{url}`", parse_mode='Markdown')
        await download_video_with_quality(chat_id, url, format_id, context, query)
    elif action == 'images':
        url_id = callback_parts[1]
        url = get_url_from_context(url_id)
        await query.edit_message_text(f"🖼️ **Baixando imagens...**\n\n📎 `{url}`", parse_mode='Markdown')
        await download_images_from_callback(chat_id, url, context, query)
    elif action == 'queue_add':
         download_type = callback_parts[1]
         url_id = callback_parts[2]
         url = get_url_from_context(url_id)
         user_name = query.from_user.first_name or "Usuário"
         
         item = await add_to_queue(chat_id, url, download_type, user_name)
         
         type_emojis = {'video': '🎬', 'images': '🖼️', 'audio': '🎵'}
         type_emoji = type_emojis.get(download_type, '📁')
         
         await query.edit_message_text(
             f"📋 **Adicionado à fila!**\n\n"
             f"{type_emoji} {download_type.title()}\n"
             f"📍 Posição: {len([i for i in download_queue if i.status == 'pending'])}\n\n"
             f"Use /queue para gerenciar sua fila",
             parse_mode='Markdown'
         )
         
         # Inicia processamento se não estiver rodando
         if not is_queue_processing():
             asyncio.create_task(process_download_queue(context))
    elif action == 'queue_refresh':
         # Atualiza a visualização da fila
         await query.answer("🔄 Atualizando fila...")
         # Chama show_queue novamente
         update_obj = type('obj', (object,), {'message': type('obj', (object,), {'chat_id': chat_id})})()
         await show_queue(update_obj, context)
    elif action == 'queue_clear_completed':
         # Remove itens concluídos da fila
         async with queue_lock:
             completed_count = len([item for item in download_queue if item.chat_id == chat_id and item.status == 'completed'])
             download_queue[:] = [item for item in download_queue if not (item.chat_id == chat_id and item.status == 'completed')]
             save_queue()
         
         await query.answer(f"🗑️ {completed_count} itens concluídos removidos")
    elif action == 'queue_clear_all':
         # Remove todos os itens do usuário
         async with queue_lock:
             user_count = len([item for item in download_queue if item.chat_id == chat_id])
             download_queue[:] = [item for item in download_queue if item.chat_id != chat_id]
             save_queue()
         
         await query.answer(f"🗑️ {user_count} itens removidos da fila")
         await query.edit_message_text(
             "📭 **Fila limpa!**\n\nTodos os seus downloads foram removidos da fila.",
             parse_mode='Markdown'
         )
    elif action == 'cut_now':
         # Executa corte imediatamente
         start_time = callback_parts[1]
         end_time = callback_parts[2]
         url_id = callback_parts[3]
         url = get_url_from_context(url_id)
         
         await query.edit_message_text(
             f"✂️ **Cortando vídeo...**\n\n"
             f"⏰ Trecho: {start_time} - {end_time}\n"
             f"📎 `{url[:50]}...`",
             parse_mode='Markdown'
         )
         
         success = await execute_video_cut(chat_id, url, start_time, end_time, context)
         
    elif action == 'cut_queue':
         # Adiciona corte à fila
         start_time = callback_parts[1]
         end_time = callback_parts[2]
         url_id = callback_parts[3]
         url = get_url_from_context(url_id)
         user_name = query.from_user.first_name or "Usuário"
         
         # Cria item especial para corte
         item = await add_to_queue(chat_id, url, 'video_cut', user_name)
         item.format_id = f"{start_time}:{end_time}"  # Armazena tempos no format_id
         save_queue()
         
         await query.edit_message_text(
             f"📋 **Corte adicionado à fila!**\n\n"
             f"✂️ Corte de vídeo\n"
             f"⏰ Trecho: {start_time} - {end_time}\n"
             f"📍 Posição: {len([i for i in download_queue if i.status == 'pending'])}\n\n"
             f"Use /queue para gerenciar sua fila",
             parse_mode='Markdown'
         )
         
         # Inicia processamento se não estiver rodando
         if not is_queue_processing():
             asyncio.create_task(process_download_queue(context))
             
    elif action == 'cut_quality':
         # Mostra qualidades para corte
         start_time = callback_parts[1]
         end_time = callback_parts[2]
         url_id = callback_parts[3]
         url = get_url_from_context(url_id)
         
         await query.edit_message_text(
             f"🎬 **Verificando qualidades...**\n\n"
             f"✂️ Corte: {start_time} - {end_time}\n"
             f"📎 `{url[:50]}...`",
             parse_mode='Markdown'
         )
         
         # Obtém qualidades disponíveis
         qualities = await get_video_qualities(url)
         
         if qualities:
             keyboard = []
             
             for quality in qualities[:6]:
                 keyboard.append([
                     InlineKeyboardButton(
                         f"✂️ {quality['quality']} - {quality['size']}",
                         callback_data=f"cut_with_quality:{quality['format_id']}:{start_time}:{end_time}:{url_id}"
                     )
                 ])
             
             keyboard.append([
                 InlineKeyboardButton("⭐ Melhor Qualidade", callback_data=f"cut_with_quality:best:{start_time}:{end_time}:{url_id}")
             ])
             
             reply_markup = InlineKeyboardMarkup(keyboard)
             
             await query.edit_message_text(
                 f"🎬 **Escolha a qualidade para o corte:**\n\n"
                 f"✂️ Trecho: {start_time} - {end_time}\n"
                 f"📎 `{url[:50]}...`",
                 reply_markup=reply_markup,
                 parse_mode='Markdown'
             )
         else:
             # Se não conseguir obter qualidades, usa padrão
             await execute_video_cut(chat_id, url, start_time, end_time, context)
             
    elif action == 'cut_with_quality':
         # Executa corte com qualidade específica
         quality_format = callback_parts[1]
         start_time = callback_parts[2]
         end_time = callback_parts[3]
         url_id = callback_parts[4]
         url = get_url_from_context(url_id)
         
         await query.edit_message_text(
             f"✂️ **Cortando com qualidade selecionada...**\n\n"
             f"📺 Qualidade: {quality_format}\n"
             f"⏰ Trecho: {start_time} - {end_time}\n"
             f"📎 `{url[:50]}...`",
             parse_mode='Markdown'
         )
         
         format_selector = quality_format if quality_format != 'best' else 'best[filesize<40M]/best[height<=480]/worst'
         success = await execute_video_cut(chat_id, url, start_time, end_time, context, format_selector)

def main() -> None:
    """Inicia o bot."""
    # Pega o token da variável de ambiente
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise ValueError("Token do Telegram não encontrado! Defina a variável de ambiente TELEGRAM_TOKEN.")

    # Cria a aplicação do bot
    application = Application.builder().token(token).build()

    # Carrega a fila de downloads
    load_queue()
    
    # Executa limpeza inicial de arquivos temporários
    try:
        files_removed = cleanup_temp_files()
        if files_removed > 0:
            logger.info(f"Limpeza inicial: {files_removed} arquivos temporários removidos")
    except Exception as e:
        logger.warning(f"Erro na limpeza inicial: {e}")
    
    # Adiciona os handlers (comandos e mensagens)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("images", download_images))
    application.add_handler(CommandHandler("queue", show_queue))
    application.add_handler(CommandHandler("clear_queue", clear_queue))
    application.add_handler(CommandHandler("cleanup", cleanup_files))
    application.add_handler(CommandHandler("cut", cut_video))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.VIDEO, handle_video_file))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

    # Inicia o bot
    logger.info("Bot iniciado e aguardando mensagens...")
    application.run_polling()

if __name__ == '__main__':
    main()
