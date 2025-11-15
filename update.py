import os
import json
import subprocess
import sys
import time
import re

try:
    import requests
    print("[Carregador] 'requests' encontrado.")
except ImportError:
    print("[Carregador] 'requests' não encontrado. Tentando instalar...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
        import requests
        print("[Carregador] 'requests' instalado e importado com sucesso.")
    except Exception as e:
        print(f"[Carregador] ERRO FATAL: Falha ao instalar 'requests'. {e}")
        time.sleep(10)
        sys.exit(1)

UPDATER_VERSION_URL = "https://gist.githubusercontent.com/assuerogames/7359d09d756320187d55fa7ff9aad4d2/raw/updater_version.json" 

CORE_UPDATER_FILE = "core_update.py"
LOCAL_CORE_VERSION_FILE = "core_updater_version.json"
BASE_DIR = os.path.dirname(__file__)

def version_key(v_str):
    """Converte 'v1.2.3' para (1, 2, 3) para comparação."""
    match = re.search(r'(\d+)\.(\d+)(?:\.(\d+))?', v_str)
    if match:
        parts = match.groups()
        return tuple(int(p) if p is not None else 0 for p in parts)
    return (0, 0, 0)

def get_local_version():
    """Lê a versão local do core-updater."""
    path = os.path.join(BASE_DIR, LOCAL_CORE_VERSION_FILE)
    if not os.path.exists(path):
        return "v0.0.0"
    try:
        with open(path, 'r') as f:
            return json.load(f).get("current_version", "v0.0.0")
    except Exception as e:
        print(f"[Carregador] Erro ao ler versão local: {e}. Forçando atualização.")
        return "v0.0.0"

def download_file(url, path, filename):
    """Baixa um arquivo."""
    print(f"[Carregador] Baixando {filename}...")
    try:
        headers = {'User-Agent': 'RaposoLauncher-Bootstrapper-v1.2', 'Cache-Control': 'no-cache', 'Pragma': 'no-cache', 'Expires': '0'}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        with open(path, 'wb') as f:
            f.write(resp.content)
        print(f"[Carregador] {filename} baixado com sucesso.")
        return True
    except Exception as e:
        print(f"[Carregador] ERRO ao baixar {filename}: {e}")
        return False

def execute_core_updater():
    """Executa o script core_update.py e fecha este carregador."""
    print(f"[Carregador] Iniciando {CORE_UPDATER_FILE}...")
    core_path = os.path.join(BASE_DIR, CORE_UPDATER_FILE)
    
    if not os.path.exists(core_path):
        print(f"[Carregador] ERRO FATAL: {CORE_UPDATER_FILE} não encontrado.")
        print("[Carregador] Não foi possível baixar o atualizador principal.")
        print("[Carregador] Verifique sua conexão ou a URL no 'update.py'.")
        time.sleep(15)
        sys.exit(1)

    try:
        # Inicia o core_update.py como um processo separado
        subprocess.Popen([sys.executable, core_path])
        # Sai do carregador (processo atual)
        sys.exit(0)
    except Exception as e:
        print(f"[Carregador] ERRO FATAL ao executar {CORE_UPDATER_FILE}: {e}")
        time.sleep(15)
        sys.exit(1)

def main():
    """Função principal do Carregador."""
    
    if UPDATER_VERSION_URL == "URL_PARA_SEU_updater_version.json":
        print("="*50)
        print("[Carregador] ERRO DE CONFIGURAÇÃO")
        print("[Carregador] A URL 'UPDATER_VERSION_URL' não foi definida.")
        print("[Carregador] Edite o 'update.py' e insira a URL correta.")
        print("="*50)
        print("[Carregador] Tentando executar o core-updater local (se existir)...")
        time.sleep(5)
        execute_core_updater()
        return

    try:
        # 1. Obter versões
        local_version = get_local_version()
        print(f"[Carregador] Versão local do Core: {local_version}")
        
        headers = {'User-Agent': 'RaposoLauncher-Bootstrapper-v1.2', 'Cache-Control': 'no-cache', 'Pragma': 'no-cache', 'Expires': '0'}
        resp = requests.get(UPDATER_VERSION_URL, headers=headers, timeout=5)
        resp.raise_for_status()
        remote_data = resp.json()
        
        remote_version = remote_data.get("latest_version")
        files_to_check = remote_data.get("files_to_check", [])
        
        if not remote_version or not files_to_check:
            raise Exception("JSON de versão remoto está mal formatado.")
        
        print(f"[Carregador] Versão remota do Core: {remote_version}")

        # 2. Comparar
        core_path = os.path.join(BASE_DIR, CORE_UPDATER_FILE)
        needs_update = version_key(remote_version) > version_key(local_version)
        is_missing = not os.path.exists(core_path)

        if needs_update or is_missing:
            if is_missing:
                print(f"[Carregador] {CORE_UPDATER_FILE} não encontrado (provavelmente primeira execução).")
            else:
                print(f"[Carregador] Nova versão do Core encontrada ({remote_version}). Atualizando...")
            
            # 3. Baixar arquivos (core_update.py, dependencias.fox)
            for file_info in files_to_check:
                file_name = file_info.get("file_name")
                file_url = file_info.get("url")
                if not file_name or not file_url:
                    continue
                
                local_path = os.path.join(BASE_DIR, file_name)
                download_file(file_url, local_path, file_name)
            
            # 4. Salvar nova versão local
            version_path = os.path.join(BASE_DIR, LOCAL_CORE_VERSION_FILE)
            try:
                with open(version_path, 'w') as f:
                    json.dump({"current_version": remote_version}, f)
                print(f"[Carregador] Core atualizado para {remote_version}.")
            except Exception as e:
                print(f"[Carregador] AVISO: Falha ao salvar {LOCAL_CORE_VERSION_FILE}: {e}")
        else:
            print("[Carregador] O 'core_update.py' já está atualizado.")
    
    except Exception as e:
        print(f"[Carregador] ERRO durante a verificação do Core: {e}")
        print("[Carregador] Tentando executar a versão local (se existir)...")

    # 5. Executar o Core (sempre tenta executar após a verificação)
    execute_core_updater()

if __name__ == "__main__":
    print("--- Iniciando Carregador do Raposo Launcher ---")

    main()
