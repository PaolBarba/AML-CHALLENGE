"""Run with: python -m uvicorn challenge.api:app --host 127.0.0.1 --port 8000."""
import asyncio
import base64
import io
import json
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from PIL import Image
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .server import MAX_BODY, REFERENCE
from .store import Invalid, Store


class ReferenceSubmission(BaseModel):
    batch_id: str = Field(min_length=1, max_length=80)
    edited_image: str = Field(max_length=24_000_000, description='Base64-encoded RGB PNG at source resolution')


def create_app(data='.challenge'):
    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(data)
        try:
            yield
        finally:
            app.state.store.db.close()

    app = FastAPI(title='Challenge reference API', lifespan=lifespan)
    bearer = HTTPBearer(auto_error=False)

    def identity(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if credentials is None or len(credentials.credentials) > 1024:
            raise HTTPException(401, 'Provide an Authorization: Bearer team-token header')
        team, admin = request.app.state.store.authenticate(credentials.credentials)
        if not team:
            raise HTTPException(401, 'Invalid authentication token')
        return team, admin

    @app.middleware('http')
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse({'error': exc.detail}, status_code=exc.status_code)

    @app.exception_handler(Invalid)
    async def invalid(request, exc):
        return JSONResponse({'error': str(exc)}, status_code=400)

    @app.exception_handler(PermissionError)
    async def forbidden(request, exc):
        return JSONResponse({'error': str(exc)}, status_code=403)

    @app.get('/api/reference/json')
    def load_image(request: Request, who=Depends(identity)):
        store = request.app.state.store
        window = store.reference_window(who[0])
        window['image_url'] = '/api/reference/json'
        if not window['available']:
            return JSONResponse(dict(window, error='Reference image is locked until the next window'), status_code=423)
        raw = REFERENCE.read_bytes()
        with Image.open(io.BytesIO(raw)) as image:
            width, height = image.size
        batch_id = store.issue_reference_batch(who[0], raw, width, height, window['next_change_at'])
        return dict(window, batch_id=batch_id, reference_id='backpack_reference', filename='image.png',
                    content_type='image/png', encoding='base64', image_width=width, image_height=height,
                    image=base64.b64encode(raw).decode('ascii'))

    @app.post('/api/reference/submissions', status_code=201, openapi_extra={
        'requestBody': {'required': True, 'content': {'application/json': {'schema': ReferenceSubmission.model_json_schema()}}}
    })
    async def upload_edited_image(request: Request, who=Depends(identity)):
        if who[1]:
            raise HTTPException(403, 'Use a team token to submit a reference edit')
        if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
            raise HTTPException(415, 'Content-Type must be application/json')
        body = bytearray()
        try:
            async with asyncio.timeout(60):
                async for chunk in request.stream():
                    if len(body) + len(chunk) > MAX_BODY:
                        raise HTTPException(413, 'Request body exceeds 32 MB')
                    body.extend(chunk)
        except TimeoutError:
            raise HTTPException(408, 'Upload exceeded 60 seconds')
        try:
            payload = ReferenceSubmission.model_validate(json.loads(body))
        except ValueError:
            raise HTTPException(400, 'Provide a JSON object containing batch_id and edited_image strings')
        return await run_in_threadpool(request.app.state.store.submit_reference, payload.model_dump(), *who)

    return app


app = create_app(os.environ.get('CHALLENGE_DATA', '.challenge'))
