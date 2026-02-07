import logging
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.persistence.db import async_session
from app.persistence.models import ChatSession, ChatMessage
from app.flow.orchestrator import handle_query

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket, user_id: int = 1):
    await websocket.accept()
    logger.info("Conexión WebSocket establecida para usuario %d", user_id)

    # Create or get chat session
    async with async_session() as session:
        chat_session = ChatSession(user_id=user_id)
        session.add(chat_session)
        await session.commit()
        await session.refresh(chat_session)
        session_id = chat_session.id

    logger.info("Sesión de chat creada: #%d", session_id)

    try:
        while True:
            data = await websocket.receive_text()
            logger.info("Mensaje recibido del usuario %d: '%s'", user_id, data)

            try:
                message = json.loads(data)
                query = message.get("message", data)
            except json.JSONDecodeError:
                query = data

            # Save user message
            async with async_session() as session:
                user_msg = ChatMessage(
                    session_id=session_id,
                    role="user",
                    content=query,
                )
                session.add(user_msg)
                await session.commit()

            # Process with orchestrator
            async with async_session() as session:
                result = await handle_query(
                    query=query,
                    user_id=user_id,
                    session=session,
                    session_id=session_id,
                )

            # Save assistant message
            async with async_session() as session:
                assistant_msg = ChatMessage(
                    session_id=session_id,
                    role="assistant",
                    content=result.response,
                )
                session.add(assistant_msg)
                await session.commit()

            # Send response (only user-facing data, no internal metadata)
            response_data = {
                "response": result.response,
            }
            if result.books:
                response_data["books"] = result.books

            await websocket.send_text(json.dumps(response_data, ensure_ascii=False))
            logger.info("Respuesta enviada al usuario %d", user_id)

    except WebSocketDisconnect:
        logger.info("Conexión WebSocket cerrada para usuario %d", user_id)
