import os
import json
import time
import uuid
import hmac
import base64
import hashlib
import sqlite3
import urllib.parse
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Depends, Header, Request, status
from pydantic import BaseModel

import webauthn
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    AuthenticatorAttachment,
    UserVerificationRequirement,
    PublicKeyCredentialDescriptor,
    COSEAlgorithmIdentifier,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url, options_to_json

# Paths & Security Configurations
AUTH_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "auth.db")
SECRET_KEY = os.environ.get("DATABRIDGE_SECRET_KEY", "databridge_super_secure_biometric_jwt_secret_key_2026")
ACCESS_TOKEN_EXPIRE_DAYS = 14

router = APIRouter(prefix="/api/auth", tags=["auth"])

def get_auth_db():
    os.makedirs(os.path.dirname(AUTH_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(AUTH_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_auth_db():
    conn = get_auth_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            display_name TEXT,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            role TEXT DEFAULT 'admin',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS webauthn_credentials (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            public_key TEXT NOT NULL,
            sign_count INTEGER DEFAULT 0,
            device_name TEXT,
            aaguid TEXT,
            transports TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS auth_challenges (
            id TEXT PRIMARY KEY,
            challenge TEXT NOT NULL,
            user_id TEXT,
            action TEXT NOT NULL,
            rp_id TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    conn.commit()
    conn.close()

# Initialize DB on load
init_auth_db()

# --- Password & Token Helpers ---
def base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode('utf-8').rstrip('=')

def base64url_decode(s: str) -> bytes:
    padding = 4 - (len(s) % 4)
    if padding != 4:
        s += '=' * padding
    return base64.urlsafe_b64decode(s)

def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    if not salt:
        salt = os.urandom(16).hex()
    pwd_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    ).hex()
    return pwd_hash, salt

def verify_password(password: str, pwd_hash: str, salt: str) -> bool:
    expected_hash, _ = hash_password(password, salt)
    return hmac.compare_digest(expected_hash, pwd_hash)

def create_access_token(user_id: str, username: str, role: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    exp = int(time.time()) + (ACCESS_TOKEN_EXPIRE_DAYS * 86400)
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "exp": exp,
        "iat": int(time.time()),
    }
    h_b64 = base64url_encode(json.dumps(header, separators=(',', ':')).encode('utf-8'))
    p_b64 = base64url_encode(json.dumps(payload, separators=(',', ':')).encode('utf-8'))
    signing_input = f"{h_b64}.{p_b64}".encode('utf-8')
    sig = hmac.new(SECRET_KEY.encode('utf-8'), signing_input, hashlib.sha256).digest()
    sig_b64 = base64url_encode(sig)
    return f"{h_b64}.{p_b64}.{sig_b64}"

def decode_access_token(token: str) -> Dict[str, Any]:
    parts = token.split('.')
    if len(parts) != 3:
        raise ValueError("Invalid token format")
    h_b64, p_b64, sig_b64 = parts
    signing_input = f"{h_b64}.{p_b64}".encode('utf-8')
    expected_sig = hmac.new(SECRET_KEY.encode('utf-8'), signing_input, hashlib.sha256).digest()
    actual_sig = base64url_decode(sig_b64)
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("Signature verification failed")
    payload = json.loads(base64url_decode(p_b64).decode('utf-8'))
    if payload.get("exp", 0) < time.time():
        raise ValueError("Token has expired")
    return payload

def get_rp_id_and_origin(request: Request) -> Tuple[str, str]:
    """Dynamically determine RP ID and expected origin based on request headers."""
    # Check Origin header, then Referer, then Host
    origin = request.headers.get("origin")
    if not origin:
        referer = request.headers.get("referer")
        if referer:
            parsed = urllib.parse.urlparse(referer)
            origin = f"{parsed.scheme}://{parsed.netloc}"
    
    if not origin:
        host = request.headers.get("host", "localhost:8000")
        scheme = "https" if request.headers.get("x-forwarded-proto") == "https" else "http"
        origin = f"{scheme}://{host}"

    parsed_origin = urllib.parse.urlparse(origin)
    rp_id = parsed_origin.hostname or "localhost"
    
    return rp_id, origin

# --- Dependency: Current User ---
def get_current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        conn = get_auth_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as count FROM users")
        user_count = cur.fetchone()["count"]
        conn.close()
        if user_count == 0:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Setup required: Please create the administrator account.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ")[1]
    try:
        payload = decode_access_token(token)
        user_id: str = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    conn = get_auth_db()
    cur = conn.cursor()
    cur.execute("SELECT id, username, display_name, role FROM users WHERE id = ?", (user_id,))
    user = cur.fetchone()
    conn.close()

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return dict(user)

def get_optional_user(authorization: Optional[str] = Header(None)) -> Optional[Dict[str, Any]]:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        return get_current_user(authorization)
    except HTTPException:
        return None

# --- Models ---
class SetupPayload(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = "Admin"

class LoginPayload(BaseModel):
    username: str
    password: str

class VerifyRegistrationPayload(BaseModel):
    challenge_id: str
    credential: Dict[str, Any]
    device_name: Optional[str] = "Mobile Phone (Biometrics)"

class VerifyLoginPayload(BaseModel):
    challenge_id: str
    credential: Dict[str, Any]

class LoginOptionsPayload(BaseModel):
    username: Optional[str] = None

# --- Endpoints ---
@router.get("/status")
def auth_status(user: Optional[Dict[str, Any]] = Depends(get_optional_user)):
    conn = get_auth_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as count FROM users")
    user_count = cur.fetchone()["count"]

    cur.execute("SELECT COUNT(*) as count FROM webauthn_credentials")
    cred_count = cur.fetchone()["count"]
    conn.close()

    return {
        "auth_configured": user_count > 0,
        "user_count": user_count,
        "has_biometric_credentials": cred_count > 0,
        "current_user": user,
    }

@router.post("/setup")
def initial_setup(payload: SetupPayload):
    conn = get_auth_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as count FROM users")
    if cur.fetchone()["count"] > 0:
        conn.close()
        raise HTTPException(status_code=400, detail="Setup already completed. Please log in.")

    if not payload.username or len(payload.username.strip()) < 3:
        conn.close()
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters.")
    if not payload.password or len(payload.password) < 4:
        conn.close()
        raise HTTPException(status_code=400, detail="Password/PIN must be at least 4 characters.")

    user_id = str(uuid.uuid4())
    pwd_hash, salt = hash_password(payload.password)

    cur.execute(
        "INSERT INTO users (id, username, display_name, password_hash, salt, role) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, payload.username.strip(), payload.display_name or "Administrator", pwd_hash, salt, "admin")
    )
    conn.commit()
    conn.close()

    token = create_access_token(user_id, payload.username.strip(), "admin")
    return {
        "message": "Admin account created successfully",
        "access_token": token,
        "user": {
            "id": user_id,
            "username": payload.username.strip(),
            "display_name": payload.display_name or "Administrator",
            "role": "admin",
        }
    }

@router.post("/login")
def login(payload: LoginPayload):
    conn = get_auth_db()
    cur = conn.cursor()
    cur.execute("SELECT id, username, display_name, password_hash, salt, role FROM users WHERE username = ?", (payload.username.strip(),))
    user = cur.fetchone()
    conn.close()

    if not user or not verify_password(payload.password, user["password_hash"], user["salt"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_access_token(user["id"], user["username"], user["role"])
    return {
        "access_token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "role": user["role"],
        }
    }

# --- WebAuthn / Passkeys Biometrics ---
@router.get("/webauthn/register-options")
def webauthn_register_options(request: Request, current_user: Dict[str, Any] = Depends(get_current_user)):
    rp_id, origin = get_rp_id_and_origin(request)
    user_id_bytes = current_user["id"].encode('utf-8')

    conn = get_auth_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM webauthn_credentials WHERE user_id = ?", (current_user["id"],))
    existing_creds = cur.fetchall()

    exclude_credentials = [
        PublicKeyCredentialDescriptor(id=base64url_to_bytes(row["id"]))
        for row in existing_creds
    ]

    options = webauthn.generate_registration_options(
        rp_id=rp_id,
        rp_name="DataBridge Unified Search",
        user_id=user_id_bytes,
        user_name=current_user["username"],
        user_display_name=current_user.get("display_name") or current_user["username"],
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=AuthenticatorAttachment.PLATFORM, # Mobile biometrics (Fingerprint / Face ID)
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=exclude_credentials,
        supported_pub_key_algs=[
            COSEAlgorithmIdentifier.ECDSA_SHA_256,
            COSEAlgorithmIdentifier.EDDSA,
            COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256,
        ],
    )

    challenge_id = str(uuid.uuid4())
    challenge_b64 = bytes_to_base64url(options.challenge)

    # Prune old challenges
    cutoff = time.time() - 300
    cur.execute("DELETE FROM auth_challenges WHERE created_at < ?", (cutoff,))
    cur.execute(
        "INSERT INTO auth_challenges (id, challenge, user_id, action, rp_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (challenge_id, challenge_b64, current_user["id"], "registration", rp_id, time.time())
    )
    conn.commit()
    conn.close()

    options_dict = json.loads(options_to_json(options))
    return {
        "challenge_id": challenge_id,
        "options": options_dict,
        "rp_id": rp_id,
    }

@router.post("/webauthn/register-verify")
def webauthn_register_verify(request: Request, payload: VerifyRegistrationPayload, current_user: Dict[str, Any] = Depends(get_current_user)):
    conn = get_auth_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM auth_challenges WHERE id = ? AND action = 'registration'", (payload.challenge_id,))
    stored = cur.fetchone()
    if not stored:
        conn.close()
        raise HTTPException(status_code=400, detail="Challenge expired or invalid. Please try again.")

    cur.execute("DELETE FROM auth_challenges WHERE id = ?", (payload.challenge_id,))
    conn.commit()

    rp_id, origin = get_rp_id_and_origin(request)
    expected_challenge = base64url_to_bytes(stored["challenge"])

    # Collect valid origins
    valid_origins = [
        origin,
        f"https://{rp_id}",
        f"http://{rp_id}",
        "https://onestop1-git-main-sanpixels.vercel.app",
        "https://databridge-api-pp88.onrender.com",
    ]

    try:
        verification = webauthn.verify_registration_response(
            credential=payload.credential,
            expected_challenge=expected_challenge,
            expected_rp_id=stored["rp_id"],
            expected_origin=valid_origins,
            require_user_verification=True,
        )
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=400, detail=f"Biometric registration verification failed: {str(e)}")

    cred_id = bytes_to_base64url(verification.credential_id)
    public_key = bytes_to_base64url(verification.credential_public_key)

    cur.execute(
        """
        INSERT OR REPLACE INTO webauthn_credentials 
        (id, user_id, public_key, sign_count, device_name, aaguid) 
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (cred_id, current_user["id"], public_key, verification.sign_count, payload.device_name or "Mobile Phone Biometrics", verification.aaguid)
    )
    conn.commit()
    conn.close()

    return {
        "success": True,
        "message": "Biometric device enrolled successfully!",
        "credential_id": cred_id,
    }

@router.post("/webauthn/login-options")
def webauthn_login_options(request: Request, payload: Optional[LoginOptionsPayload] = None):
    rp_id, origin = get_rp_id_and_origin(request)

    conn = get_auth_db()
    cur = conn.cursor()

    allow_credentials = None
    user_id = None
    if payload and payload.username:
        cur.execute("SELECT id FROM users WHERE username = ?", (payload.username.strip(),))
        u = cur.fetchone()
        if u:
            user_id = u["id"]
            cur.execute("SELECT id FROM webauthn_credentials WHERE user_id = ?", (user_id,))
            creds = cur.fetchall()
            allow_credentials = [
                PublicKeyCredentialDescriptor(id=base64url_to_bytes(c["id"]))
                for c in creds
            ]
    else:
        # If no username supplied, allow any registered biometric credential
        cur.execute("SELECT id FROM webauthn_credentials")
        all_creds = cur.fetchall()
        if all_creds:
            allow_credentials = [
                PublicKeyCredentialDescriptor(id=base64url_to_bytes(c["id"]))
                for c in all_creds
            ]

    options = webauthn.generate_authentication_options(
        rp_id=rp_id,
        user_verification=UserVerificationRequirement.REQUIRED,
        allow_credentials=allow_credentials,
    )

    challenge_id = str(uuid.uuid4())
    challenge_b64 = bytes_to_base64url(options.challenge)

    cutoff = time.time() - 300
    cur.execute("DELETE FROM auth_challenges WHERE created_at < ?", (cutoff,))
    cur.execute(
        "INSERT INTO auth_challenges (id, challenge, user_id, action, rp_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (challenge_id, challenge_b64, user_id, "authentication", rp_id, time.time())
    )
    conn.commit()
    conn.close()

    options_dict = json.loads(options_to_json(options))
    return {
        "challenge_id": challenge_id,
        "options": options_dict,
        "rp_id": rp_id,
    }

@router.post("/webauthn/login-verify")
def webauthn_login_verify(request: Request, payload: VerifyLoginPayload):
    conn = get_auth_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM auth_challenges WHERE id = ? AND action = 'authentication'", (payload.challenge_id,))
    stored = cur.fetchone()
    if not stored:
        conn.close()
        raise HTTPException(status_code=400, detail="Authentication challenge expired or invalid.")

    cur.execute("DELETE FROM auth_challenges WHERE id = ?", (payload.challenge_id,))
    conn.commit()

    cred_raw_id = payload.credential.get("id")
    if not cred_raw_id:
        conn.close()
        raise HTTPException(status_code=400, detail="Missing credential ID in response.")

    cur.execute("""
        SELECT c.*, u.id as u_id, u.username, u.display_name, u.role
        FROM webauthn_credentials c
        JOIN users u ON c.user_id = u.id
        WHERE c.id = ?
    """, (cred_raw_id,))
    cred_row = cur.fetchone()

    if not cred_row:
        conn.close()
        raise HTTPException(status_code=400, detail="Biometric credential not recognized.")

    rp_id, origin = get_rp_id_and_origin(request)
    expected_challenge = base64url_to_bytes(stored["challenge"])
    credential_public_key = base64url_to_bytes(cred_row["public_key"])

    valid_origins = [
        origin,
        f"https://{rp_id}",
        f"http://{rp_id}",
        "https://onestop1-git-main-sanpixels.vercel.app",
        "https://databridge-api-pp88.onrender.com",
    ]

    try:
        verification = webauthn.verify_authentication_response(
            credential=payload.credential,
            expected_challenge=expected_challenge,
            expected_rp_id=stored["rp_id"],
            expected_origin=valid_origins,
            credential_public_key=credential_public_key,
            credential_current_sign_count=cred_row["sign_count"],
            require_user_verification=True,
        )
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=400, detail=f"Biometric verification failed: {str(e)}")

    # Update sign count
    cur.execute("UPDATE webauthn_credentials SET sign_count = ? WHERE id = ?", (verification.new_sign_count, cred_raw_id))
    conn.commit()
    conn.close()

    token = create_access_token(cred_row["u_id"], cred_row["username"], cred_row["role"])
    return {
        "success": True,
        "access_token": token,
        "user": {
            "id": cred_row["u_id"],
            "username": cred_row["username"],
            "display_name": cred_row["display_name"],
            "role": cred_row["role"],
        }
    }

@router.get("/me")
def get_profile(current_user: Dict[str, Any] = Depends(get_current_user)):
    conn = get_auth_db()
    cur = conn.cursor()
    cur.execute("SELECT id, device_name, created_at FROM webauthn_credentials WHERE user_id = ?", (current_user["id"],))
    devices = [dict(row) for row in cur.fetchall()]
    conn.close()

    return {
        "user": current_user,
        "enrolled_devices": devices,
    }

@router.delete("/credentials/{credential_id}")
def delete_credential(credential_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    conn = get_auth_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM webauthn_credentials WHERE id = ? AND user_id = ?", (credential_id, current_user["id"]))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Biometric device removed"}
