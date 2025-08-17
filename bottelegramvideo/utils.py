import logging
import os
import time
from datetime import datetime
from PIL import Image

# Configura o logger
logger = logging.getLogger(__name__)

# Funções de Feedback Visual
def create_progress_bar(percentage, length=10):
    """Cria uma barra de progresso visual."""
    filled = int(length * percentage / 100)
    bar = '█' * filled + '░' * (length - filled)
    return f"[{bar}] {percentage}%"

def get_loading_emoji(step=0):
    """Retorna emojis animados para loading."""
    emojis = ['⏳', '⌛', '🔄', '⚡']
    return emojis[step % len(emojis)]

def get_status_emoji(status):
    """Retorna emoji baseado no status."""
    status_emojis = {
        'starting': '🚀',
        'downloading': '⬇️',
        'processing': '⚙️',
        'uploading': '⬆️',
        'completed': '✅',
        'error': '❌',
        'warning': '⚠️',
        'info': 'ℹ️'
    }
    return status_emojis.get(status, '📱')

async def send_progress_message(context, chat_id, message, status='info', progress=None):
    """Envia mensagem com feedback visual melhorado."""
    emoji = get_status_emoji(status)
    
    if progress is not None:
        progress_bar = create_progress_bar(progress)
        text = f"{emoji} **{message}**\n\n{progress_bar}"
    else:
        text = f"{emoji} **{message}**"
    
    try:
        await context.bot.send_message(
            chat_id,
            text=text,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem de progresso: {e}")

# Funções de Validação e Detecção
def is_good_quality_image(image_path):
    """Verifica se a imagem tem boa qualidade baseada no tamanho."""
    try:
        with Image.open(image_path) as img:
            width, height = img.size
            file_size = os.path.getsize(image_path)
            
            # Critérios de qualidade:
            # - Resolução mínima: 200x200
            # - Tamanho mínimo: 10KB
            # - Não muito pequena em relação ao tamanho do arquivo
            min_resolution = width >= 200 and height >= 200
            min_file_size = file_size >= 10240  # 10KB
            good_ratio = file_size / (width * height) > 0.01  # Evita imagens muito comprimidas
            
            return min_resolution and min_file_size and good_ratio
    except Exception as e:
        logger.warning(f"Erro ao verificar qualidade da imagem {image_path}: {e}")
        return False

def is_story_url(url):
    """Detecta se a URL é de um Story do Instagram ou Facebook."""
    story_patterns = [
        '/stories/',
        '/story/',
        'instagram.com/stories/',
        'facebook.com/stories/',
        'fb.watch/story/'
    ]
    
    url_lower = url.lower()
    return any(pattern in url_lower for pattern in story_patterns)

# Funções de Tempo
def parse_time_to_seconds(time_str):
    """Converte string de tempo para segundos."""
    try:
        # Remove espaços e converte para minúsculas
        time_str = time_str.strip().lower()
        
        # Se já é um número (segundos)
        if time_str.isdigit():
            return int(time_str)
        
        # Formato HH:MM:SS
        if time_str.count(':') == 2:
            h, m, s = map(int, time_str.split(':'))
            return h * 3600 + m * 60 + s
        
        # Formato MM:SS
        elif time_str.count(':') == 1:
            m, s = map(int, time_str.split(':'))
            return m * 60 + s
        
        else:
            raise ValueError("Formato inválido")
    except ValueError:
        raise ValueError(f"Formato de tempo inválido: {time_str}")

def format_seconds_to_time(seconds):
    """Converte segundos para formato HH:MM:SS."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}"

# Funções de Limpeza
def cleanup_temp_files():
    """Remove arquivos temporários antigos (mais de 1 hora)."""
    try:
        current_time = time.time()
        removed_count = 0
        
        # Padrões de arquivos temporários
        temp_patterns = [
            '*.mp4', '*.webm', '*.mkv', '*.avi', '*.mov',
            '*.jpg', '*.jpeg', '*.png', '*.webp', '*.gif',
            '*_thumb.jpg', '*_part*.mp4', '*_cut*.mp4',
            '*_img*.jpg', '*_img*.png', '*_story*.*'
        ]
        
        for pattern in temp_patterns:
            import glob
            for file_path in glob.glob(pattern):
                try:
                    # Verifica se o arquivo é antigo (mais de 1 hora)
                    file_time = os.path.getmtime(file_path)
                    if current_time - file_time > 3600:  # 1 hora
                        os.remove(file_path)
                        removed_count += 1
                        logger.info(f"Arquivo temporário removido: {file_path}")
                except Exception as e:
                    logger.warning(f"Erro ao remover {file_path}: {e}")
        
        logger.info(f"Limpeza concluída: {removed_count} arquivos removidos")
        return removed_count
        
    except Exception as e:
        logger.error(f"Erro na limpeza de arquivos temporários: {e}")
        return 0

def force_cleanup_temp_files():
    """Remove todos os arquivos temporários, independente da idade."""
    try:
        removed_count = 0
        
        # Padrões de arquivos temporários
        temp_patterns = [
            '*.mp4', '*.webm', '*.mkv', '*.avi', '*.mov',
            '*.jpg', '*.jpeg', '*.png', '*.webp', '*.gif',
            '*_thumb.jpg', '*_part*.mp4', '*_cut*.mp4',
            '*_img*.jpg', '*_img*.png', '*_story*.*'
        ]
        
        for pattern in temp_patterns:
            import glob
            for file_path in glob.glob(pattern):
                try:
                    os.remove(file_path)
                    removed_count += 1
                    logger.info(f"Arquivo temporário removido: {file_path}")
                except Exception as e:
                    logger.warning(f"Erro ao remover {file_path}: {e}")
        
        logger.info(f"Limpeza forçada concluída: {removed_count} arquivos removidos")
        return removed_count
        
    except Exception as e:
        logger.error(f"Erro na limpeza forçada: {e}")
        return 0

# Função para verificar FFmpeg
async def check_ffmpeg():
    """Verifica se o FFmpeg está disponível."""
    try:
        import subprocess
        result = subprocess.run(['ffmpeg', '-version'], 
                              capture_output=True, 
                              text=True, 
                              timeout=10)
        return result.returncode == 0
    except Exception:
        return False