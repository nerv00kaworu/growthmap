"""Fail-closed loader for generated public payment coordinates."""
from __future__ import annotations
import hashlib,json,os,stat,unicodedata
from pathlib import Path
from ._public_config_digest import PUBLIC_CONFIG_SHA256
_CONFIG_PATH=Path(__file__).parents[1]/"public-config.json"
_EXACT_KEYS={"baseNetwork","basePayee"}
_MAX_BYTES=4096

def _pairs(items):
 result={};exact=set();folded=set()
 for key,value in items:
  if not isinstance(key,str):raise RuntimeError("payment public config key mismatch")
  normalized=unicodedata.normalize("NFKC",key).casefold()
  if key in exact:raise RuntimeError("payment public config duplicate key")
  if normalized in folded:raise RuntimeError("payment public config key collision")
  exact.add(key);folded.add(normalized);result[key]=value
 return result

def load_public_config(path:Path=_CONFIG_PATH,*,expected_digest:str=PUBLIC_CONFIG_SHA256)->dict[str,str]:
 flags=os.O_RDONLY|getattr(os,"O_CLOEXEC",0)|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_NONBLOCK",0)
 try:
  fd=os.open(path,flags)
 except OSError as error:raise RuntimeError("payment public config is not a safe regular file") from error
 try:
  opened=os.fstat(fd)
  try:listed=os.stat(path,follow_symlinks=False)
  except OSError as error:raise RuntimeError("payment public config changed during open") from error
  if not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(listed.st_mode) or (opened.st_dev,opened.st_ino)!=(listed.st_dev,listed.st_ino):raise RuntimeError("payment public config is not a stable regular file")
  if opened.st_uid not in {os.getuid(),0}:raise RuntimeError("payment public config owner is not trusted")
  if opened.st_mode&(stat.S_IWGRP|stat.S_IWOTH):raise RuntimeError("payment public config permissions are unsafe")
  if opened.st_size<=0 or opened.st_size>_MAX_BYTES:raise RuntimeError("payment public config size is invalid")
  raw=b""
  while len(raw)<=_MAX_BYTES:
   chunk=os.read(fd,min(1024,_MAX_BYTES+1-len(raw)))
   if not chunk:break
   raw+=chunk
  after=os.fstat(fd)
  try:post=os.stat(path,follow_symlinks=False)
  except OSError as error:raise RuntimeError("payment public config changed during read") from error
  identity=(opened.st_dev,opened.st_ino,opened.st_size)
  if len(raw)>_MAX_BYTES or identity!=(after.st_dev,after.st_ino,after.st_size) or identity!=(post.st_dev,post.st_ino,post.st_size):raise RuntimeError("payment public config changed during read")
 finally:os.close(fd)
 if hashlib.sha256(raw).hexdigest()!=expected_digest:raise RuntimeError("payment public config digest mismatch")
 try:data=json.loads(raw.decode("utf-8","strict"),object_pairs_hook=_pairs)
 except (UnicodeError,json.JSONDecodeError,RuntimeError) as error:raise RuntimeError("payment public config is invalid strict JSON") from error
 if not isinstance(data,dict) or set(data)!=_EXACT_KEYS or not all(type(data[k]) is str for k in _EXACT_KEYS):raise RuntimeError("payment public config shape mismatch")
 if data["baseNetwork"]!="eip155:8453" or not __import__('re').fullmatch(r"0x[0-9a-f]{40}",data["basePayee"]):raise RuntimeError("payment public config value mismatch")
 return data
PUBLIC_CONFIG=load_public_config()
APPROVED_BASE_RECIPIENT=PUBLIC_CONFIG["basePayee"]
