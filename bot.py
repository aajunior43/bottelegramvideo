import logging
import os
import subprocess
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction

# Configura o logging para debug
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Função para o comando /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envia uma mensagem de boas-vindas quando o comando /start é emitido."""
    user = update.effective_user
    await update.message.reply_html(
        f"Olá, {user.mention_html()}!\n\nEnvie-me o link de um vídeo que você deseja baixar.",
    )

# Função principal que lida com os links enviados
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Baixa o vídeo do link enviado pelo usuário."""
    chat_id = update.message.chat_id
    message_text = update.message.text
    
    # Avisa ao usuário que o processo começou
    await context.bot.send_message(chat_id, text="Processando seu link...")
    
    # Mostra a ação "enviando vídeo" no chat
    await context.bot.send_chat_action(chat_id, action=ChatAction.UPLOAD_VIDEO)

    try:
        # Define o nome do arquivo de saída. Usamos um nome fixo para facilitar.
        output_template = f"{chat_id}_{update.message.message_id}.%(ext)s"
        
        # Comando yt-dlp para baixar o melhor formato de vídeo e áudio em MP4
        command = [
            'yt-dlp',
            '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
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
                if file.startswith(f"{chat_id}_{update.message.message_id}"):
                    downloaded_file = file
                    break
            
            if downloaded_file:
                logger.info(f"Download concluído: {downloaded_file}")
                await context.bot.send_message(chat_id, text="Download finalizado! Enviando o vídeo...")
                
                # Envia o vídeo
                with open(downloaded_file, 'rb') as video_file:
                    await context.bot.send_video(chat_id, video=video_file, supports_streaming=True)
                
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

def main() -> None:
    """Inicia o bot."""
    # Pega o token da variável de ambiente
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise ValueError("Token do Telegram não encontrado! Defina a variável de ambiente TELEGRAM_TOKEN.")

    # Cria a aplicação do bot
    application = Application.builder().token(token).build()

    # Adiciona os handlers (comandos e mensagens)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

    # Inicia o bot
    logger.info("Bot iniciado e aguardando mensagens...")
    application.run_polling()

if __name__ == '__main__':
    main()
