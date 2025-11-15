import os
import json
import subprocess
import platform
import re
import requests  # Esta importação agora está segura (é instalada abaixo)
import threading
import time
import sys

# --- INÍCIO DA MELHORIA: Auto-instalação de dependências ---

# 1. Dependência CRÍTICA: requests (essencial para tudo)
try:
    import requests
    print("Biblioteca 'requests' encontrada.")
except ImportError:
    print("Aviso: Biblioteca 'requests' não encontrada. Tentando instalar...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
        print("Instalação concluída. Importando 'requests'...")
        import requests
        print("'requests' importado com sucesso!")
    except Exception as e:
        print(f"ERRO FATAL: Falha ao instalar 'requests'. {e}")
        time.sleep(10)
        sys.exit(1)

# 2. Dependência OPCIONAL: ttkbootstrap (para a GUI)
try:
    import tkinter as tk
    import ttkbootstrap as ttk
    from ttkbootstrap.constants import *
    GUI_DISPONIVEL = True
except ImportError:
    print("Aviso: TTKBootstrap não encontrado. Tentando instalar...")
    GUI_DISPONIVEL = False
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "ttkbootstrap"])
        print("Instalação concluída. Importando biblioteca...")
        import tkinter as tk
        import ttkbootstrap as ttk
        from ttkbootstrap.constants import *
        GUI_DISPONIVEL = True
        print("TTKBootstrap importado com sucesso!")
    except Exception as e:
        print(f"AVISO: Falha ao instalar TTKBootstrap. {e}. Rodando em modo terminal.")
        GUI_DISPONIVEL = False
        
# --- FIM DA MELHORIA ---


# --- CONFIGURAÇÕES OBRIGATÓRIAS ---
# Este JSON é o do LAUNCHER (cat.pyw), não o do atualizador.
VERSION_CHECK_URL = "https://gist.githubusercontent.com/assuerogames/b7060c5601dba31c60b92e3aeddc3eee/raw/raposo_version.json" 
MAIN_APP_FILE = "cat.pyw"
# --- FIM DA CONFIGURAÇÃO ---

BASE_DIR = os.path.dirname(__file__)
LOCAL_VERSION_FILE = os.path.join(BASE_DIR, "launcher_version.json")
MAIN_APP_PATH = os.path.join(BASE_DIR, MAIN_APP_FILE)
# --- NOVO: Nome do arquivo de dependências ---
DEPS_FILE_NAME = "dependencias.fox"


def version_key(v_str):
    match = re.search(r'(\d+)\.(\d+)(?:\.(\d+))?', v_str)
    if match:
        parts = match.groups()
        return tuple(int(p) if p is not None else 0 for p in parts)
    return (0, 0, 0)

class Updater(ttk.Window):
    def __init__(self):
        super().__init__(themename="cyborg")
        self.title("Raposo Launcher - Atualizador")
        self.geometry("300x100")
        self.resizable(False, False)
        # self.place_window_center() # 'place_window_center' não existe, removido
        self.status_label = ttk.Label(self, text="Verificando arquivos...", font=("-family", 10))
        self.status_label.pack(pady=20, fill="x")
        self.progressbar = ttk.Progressbar(self, mode="indeterminate", bootstyle="primary-striped")
        self.progressbar.pack(pady=5, padx=20, fill="x")
        self.progressbar.start()
        self.after(500, self.start_update_thread)

    def start_update_thread(self):
        threading.Thread(target=self.run_update_check, daemon=True).start()

    # --- INÍCIO DA NOVA FUNÇÃO (install_app_dependencies) ---
    def install_app_dependencies(self):
        """Lê o 'dependencias.fox' e instala o que falta."""
        deps_file_path = os.path.join(BASE_DIR, DEPS_FILE_NAME)
        
        if not os.path.exists(deps_file_path):
            print(f"Aviso: '{DEPS_FILE_NAME}' não encontrado. Pulando verificação de bibliotecas.")
            return

        self.update_status("Verificando bibliotecas do launcher...")
        print(f"Lendo arquivo de dependências: {deps_file_path}")
        
        try:
            with open(deps_file_path, 'r') as f:
                # Lê, remove espaços e ignora linhas vazias ou comentários
                packages = [
                    line.strip() for line in f 
                    if line.strip() and not line.strip().startswith('#')
                ]
            
            if not packages:
                print("Nenhuma biblioteca extra para instalar.")
                self.update_status("Nenhuma biblioteca extra.")
                time.sleep(0.5)
                return

            for pkg in packages:
                self.update_status(f"Verificando/Instalando {pkg}...")
                print(f"Executando: pip install {pkg}")
                try:
                    # Usamos check_call para garantir que o pip termine
                    # Escondemos a saída com 'stdout' e 'stderr' para não poluir
                    subprocess.check_call(
                        [sys.executable, "-m", "pip", "install", pkg],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                except subprocess.CalledProcessError as e:
                    print(f"Falha ao instalar {pkg}. Tentando novamente sem ocultar a saída...")
                    # Se falhar, tenta de novo mostrando o erro
                    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
            
            self.update_status("Bibliotecas extras verificadas.")
            time.sleep(1)
            
        except Exception as e:
            print(f"ERRO ao ler ou instalar dependências: {e}")
            self.update_status("Erro ao verificar bibliotecas extras.")
            time.sleep(2)
    # --- FIM DA NOVA FUNÇÃO ---

    def run_update_check(self):
        """(THREAD) Faz a verificação e atualização."""
        try:
            # 1. Pega a versão local
            local_version = "v0.0.0" 
            if os.path.exists(LOCAL_VERSION_FILE):
                try:
                    with open(LOCAL_VERSION_FILE, 'r') as f:
                        local_version = json.load(f).get("current_version", "v0.0.0")
                except Exception:
                    local_version = "v0.0.0" 
            self.update_status(f"Versão Local: {local_version}. Verificando...")

            # 2. Pega a versão remota
            headers = {'User-Agent': 'RaposoLauncher-Updater-v1', 'Cache-Control': 'no-cache', 'Pragma': 'no-cache', 'Expires': '0'}
            resp = requests.get(VERSION_CHECK_URL, headers=headers, timeout=5)
            resp.raise_for_status()
            remote_data = resp.json()
            remote_version = remote_data.get("latest_version")
            files_to_check = remote_data.get("files_to_check", []) 

            if not remote_version or not files_to_check: 
                raise Exception("JSON de versão remoto está mal formatado.")

            # 3. Compara as versões
            is_update_needed = version_key(remote_version) > version_key(local_version)
            headers_download = {'User-Agent': 'Mozilla/5.0'}
            
            if is_update_needed:
                self.update_status(f"Atualizando para {remote_version}...")
                self.after(0, self.progressbar.config, {"mode": "determinate", "maximum": len(files_to_check)})
                if GUI_DISPONIVEL:
                    self.after(0, self.progressbar.stop)
                
                # 4. Baixa e sobrescreve tudo
                for i, file_info in enumerate(files_to_check):
                    file_name = file_info.get("file_name")
                    file_url = file_info.get("url")
                    if not file_name or not file_url: continue

                    # --- ESTA É A MUDANÇA CRÍTICA ---
                    if file_name.endswith("core_update.py") or file_name.endswith("update.py"): 
                        print(f"Aviso: Pulando o '{file_name}'. (Trabalho do Carregador)")
                        self.after(0, self.progressbar.step)
                        continue 
                    # --- FIM DA MUDANÇA CRÍTICA ---
                        
                    self.update_status(f"Baixando {file_name}...")
                    local_path = os.path.join(BASE_DIR, file_name)
                    try:
                        resp_download = requests.get(file_url, headers=headers_download)
                        resp_download.raise_for_status()
                        with open(local_path, 'wb') as f: f.write(resp_download.content)
                    except Exception as e_download:
                        print(f"AVISO: Falha ao baixar {file_name}: {e_download}")
                    self.after(0, self.progressbar.step)

                # 5. Salva a nova versão
                self.update_status(f"Atualizado para {remote_version}!")
                self._write_local_version(remote_version)
                time.sleep(1)

            else:
                # Versão é a mesma. APENAS checa arquivos faltando
                self.update_status("Verificando arquivos...")
                for file_info in files_to_check:
                    file_name, file_url = file_info.get("file_name"), file_info.get("url")
                    is_executable = file_info.get("is_executable", False)
                    if not file_name or not file_url: continue
                    local_path = os.path.join(BASE_DIR, file_name)
                    if not is_executable and not os.path.exists(local_path):
                        self.update_status(f"Baixando {file_name}...")
                        resp_download = requests.get(file_url, headers=headers_download)
                        resp_download.raise_for_status()
                        with open(local_path, 'wb') as f: f.write(resp_download.content)
                self.update_status("O launcher já está atualizado.")
                time.sleep(1)
            
            # --- CHAMADA DA NOVA FUNÇÃO (ANTES DE ABRIR) ---
            self.install_app_dependencies()
            
            # 6. Inicia o launcher principal
            self.launch_main_app()

        except Exception as e:
            print(f"ERRO NO UPDATE: {e}")
            self.update_status("Erro ao atualizar. Verificando libs...")
            time.sleep(2) 
            
            # --- CHAMADA DA NOVA FUNÇÃO (MESMO COM ERRO) ---
            self.install_app_dependencies()
            
            self.launch_main_app()

    def _write_local_version(self, version):
        try:
            with open(LOCAL_VERSION_FILE, 'w') as f:
                json.dump({"current_version": version}, f)
        except Exception as e:
            print(f"AVISO: Não foi possível salvar a versão local: {e}")

    def launch_main_app(self):
        try:
            exe_path = sys.executable
            if platform.system() == "Windows":
                exe_path = exe_path.replace("python.exe", "pythonw.exe")
            print(f"Iniciando {MAIN_APP_PATH} com {exe_path}...")
            subprocess.Popen([exe_path, MAIN_APP_PATH])
            self.after(500, self.destroy)
        except Exception as e:
            self.update_status("ERRO FATAL: Não foi possível iniciar o cat.pyw!")
            print(f"ERRO AO INICIAR: {e}")
            time.sleep(5)
            self.destroy()
            
    def update_status(self, text):
        if not GUI_DISPONIVEL:
            print(f"[Updater] {text}")
            return
        try:
            self.after(0, self.status_label.config, {"text": text})
        except (tk.TclError, NameError): pass

def run_updater_no_gui():
    print("[Updater] Iniciando em modo terminal (sem GUI)...")
    class FakeApp:
        def update_status(self, text): print(f"[Updater] {text}")
        def _write_local_version(self, version):
            try:
                with open(LOCAL_VERSION_FILE, 'w') as f: json.dump({"current_version": version}, f)
            except Exception as e: print(f"AVISO: Não foi possível salvar a versão local: {e}")
        
        def launch_main_app(self):
            try:
                exe_path = sys.executable
                if platform.system() == "Windows": exe_path = exe_path.replace("python.exe", "pythonw.exe")
                print(f"Iniciando {MAIN_APP_PATH} com {exe_path}...")
                subprocess.Popen([exe_path, MAIN_APP_PATH])
            except Exception as e: print(f"ERRO FATAL: Não foi possível iniciar o cat.pyw! {e}")

        # --- INÍCIO DA NOVA FUNÇÃO (Versão NO-GUI) ---
        def install_app_dependencies(self):
            deps_file_path = os.path.join(BASE_DIR, DEPS_FILE_NAME)
            if not os.path.exists(deps_file_path):
                print(f"Aviso: '{DEPS_FILE_NAME}' não encontrado. Pulando.")
                return
            self.update_status("Verificando bibliotecas do launcher...")
            print(f"Lendo arquivo de dependências: {deps_file_path}")
            try:
                with open(deps_file_path, 'r') as f:
                    packages = [line.strip() for line in f if line.strip() and not line.startswith('#')]
                if not packages:
                    print("Nenhuma biblioteca extra para instalar.")
                    return
                for pkg in packages:
                    self.update_status(f"Verificando/Instalando {pkg}...")
                    print(f"Executando: pip install {pkg}")
                    # No modo terminal, é melhor mostrar a saída do pip
                    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
                self.update_status("Bibliotecas extras verificadas.")
            except Exception as e:
                print(f"ERRO ao ler ou instalar dependências: {e}")
                self.update_status("Erro ao verificar bibliotecas extras.")
        # --- FIM DA NOVA FUNÇÃO (Versa NO-GUI) ---

        def run_update_check(self):
            try:
                local_version = "v0.0.0" 
                if os.path.exists(LOCAL_VERSION_FILE):
                    try:
                        with open(LOCAL_VERSION_FILE, 'r') as f: local_version = json.load(f).get("current_version", "v0.0.0")
                    except Exception: local_version = "v0.0.0"
                self.update_status(f"Versão Local: {local_version}. Verificando...")
                
                headers = {'User-Agent': 'RaposoLauncher-Updater-v1', 'Cache-Control': 'no-cache', 'Pragma': 'no-cache', 'Expires': '0'}
                resp = requests.get(VERSION_CHECK_URL, headers=headers, timeout=5)
                resp.raise_for_status()
                remote_data = resp.json()
                remote_version, files_to_check = remote_data.get("latest_version"), remote_data.get("files_to_check", [])
                
                if not remote_version or not files_to_check: raise Exception("JSON de versão remoto está mal formatado.")
                
                is_update_needed = version_key(remote_version) > version_key(local_version)
                headers_download = {'User-Agent': 'Mozilla/5.0'}
                
                if is_update_needed:
                    self.update_status(f"Atualizando para {remote_version}...")
                    for i, file_info in enumerate(files_to_check):
                        file_name, file_url = file_info.get("file_name"), file_info.get("url")
                        if not file_name or not file_url: continue
                        
                        # --- ESTA É A MUDANÇA CRÍTICA ---
                        if file_name.endswith("core_update.py") or file_name.endswith("update.py"): 
                            print(f"Aviso: Pulando o '{file_name}'. (Trabalho do Carregador)")
                            continue 
                        # --- FIM DA MUDANÇA CRÍTICA ---
                        
                        self.update_status(f"Baixando {file_name}...")
                        local_path = os.path.join(BASE_DIR, file_name)
                        try:
                            resp_download = requests.get(file_url, headers=headers_download)
                            resp_download.raise_for_status()
                            with open(local_path, 'wb') as f: f.write(resp_download.content)
                        except Exception as e_download: print(f"AVISO: Falha ao baixar {file_name}: {e_download}")
                    self.update_status(f"Atualizado para {remote_version}!")
                    self._write_local_version(remote_version)
                else:
                    self.update_status("Verificando arquivos...")
                    for file_info in files_to_check:
                        file_name, file_url = file_info.get("file_name"), file_info.get("url")
                        is_executable = file_info.get("is_executable", False)
                        if not file_name or not file_url: continue
                        local_path = os.path.join(BASE_DIR, file_name)
                        if not is_executable and not os.path.exists(local_path):
                            self.update_status(f"Baixando {file_name}...")
                            resp_download = requests.get(file_url, headers=headers_download)
                            resp_download.raise_for_status()
                            with open(local_path, 'wb') as f: f.write(resp_download.content)
                    self.update_status("O launcher já está atualizado.")
                
                # --- CHAMADA DA NOVA FUNÇÃO (NO-GUI) ---
                self.install_app_dependencies()
                self.launch_main_app()
                
            except Exception as e:
                print(f"ERRO NO UPDATE: {e}")
                self.update_status("Erro ao atualizar. Verificando libs...")
                
                # --- CHAMADA DA NOVA FUNÇÃO (NO-GUI) ---
                self.install_app_dependencies()
                self.launch_main_app()

    app = FakeApp()
    app.run_update_check()

if __name__ == "__main__":
    if GUI_DISPONIVEL:
        app = Updater()
        app.mainloop()
    else:
        run_updater_no_gui()
