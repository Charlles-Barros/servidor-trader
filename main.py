import io
import os
from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel
from PIL import Image
from google import genai
from supabase import create_client, Client

app = FastAPI()

# Configuração Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Configuração Gemini API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client_gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# Lista com os modelos Gemini mais recentes e rápidos
MODELOS_GEMINI = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-3.5-flash",
    "gemini-flash-latest"
]

PROMPT_ANALISE = (
    "Análise RÁPIDA de Price Action e Suporte/Resistência.\n"
    "Examine o gráfico na imagem:\n"
    "1. Identifique o ativo visível.\n"
    "2. Recomende a melhor operação (2M ou 5M em tendências claras).\n"
    "3. Calcule a probabilidade (30% a 95%).\n\n"
    "Responda EXATAMENTE neste formato sem formatação extra:\n"
    "Ativo: [NOME] | Tempo operação: [2M ou 5M] | Ordem: [CALL ou PUT] | Probabilidade: [XX%]"
)

class LoginData(BaseModel):
    email: str
    senha: str

@app.get("/")
def home():
    return {"status": "Servidor Megalodon Online"}

@app.post("/login")
def login(data: LoginData):
    try:
        res = supabase.table("usuarios").select("*").eq("email", data.email).execute()
        if not res.data:
            raise HTTPException(status_code=401, detail="Usuário não encontrado.")
        
        user = res.data[0]
        if user.get("senha") != data.senha:
            raise HTTPException(status_code=401, detail="Senha incorreta.")
            
        return {
            "autenticado": True,
            "dias_restantes": user.get("dias_restantes", 30),
            "mensagem": "Login efetuado com sucesso."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analisar")
async def analisar(file: UploadFile = File(...)):
    if not client_gemini:
        raise HTTPException(status_code=500, detail="Chave GEMINI_API_KEY não configurada no servidor.")
        
    try:
        contents = await file.read()
        image = Image.open(io.BytesIO(contents))
        
        response = None
        for modelo in MODELOS_GEMINI:
            try:
                response = client_gemini.models.generate_content(
                    model=modelo,
                    contents=[PROMPT_ANALISE, image]
                )
                if response and response.text:
                    break
            except Exception:
                continue

        if not response or not response.text:
            raise HTTPException(status_code=500, detail="Erro ao gerar análise com os modelos disponíveis.")

        return {"analise": response.text.strip()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
