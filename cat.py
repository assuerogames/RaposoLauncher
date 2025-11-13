import os
import json
import subprocess
import platform
import zipfile
import uuid
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from tkinter import messagebox, filedialog
from io import BytesIO
import requests
import threading
from queue import Queue
import concurrent.futures
import webbrowser
import shutil
import re
import pypresence
import time


try:
    from PIL import Image, ImageTk, ImageOps
except ImportError:
    # Se o Pillow não estiver instalado, o launcher nem vai abrir
    print("ERRO CRÍTICO: A biblioteca 'Pillow' não foi encontrada.")
    print("Por favor, execute: pip install pillow")
    exit() # Fecha o script

BASE_DIR = os.path.dirname(__file__)
MODPACKS_DIR = os.path.join(BASE_DIR, "modpacks")
ACCOUNTS_FILE = os.path.join(BASE_DIR, "accounts.json")
JAVA_ROOT = os.path.join(BASE_DIR, "java")
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")

# As variáveis de JOGO (GAME_DIR, etc.) são definidas dentro da classe agora
GAME_DIR = None
VERSIONS_DIR = None
LIBRARIES_DIR = None
ASSETS_DIR = None

# (Não se esqueça de ter o 'from io import BytesIO' e 'from PIL import Image, ImageTk, ImageOps'
# no topo do seu arquivo cat.py)

class ModDownloader(tk.Toplevel):
    """Uma janela Toplevel para pesquisar e baixar mods do Modrinth,
    com uma UI inspirada no site."""
    
    def __init__(self, parent, launcher_instance, modpack_name, modpack_config):
        super().__init__(parent)
        self.title(f"Biblioteca Modrinth ({modpack_name})")
        self.geometry("900x600") 
        self.resizable(True, True) 
        self.grab_set()
        
        self.launcher = launcher_instance
        self.modpack_name = modpack_name
        
        # --- NOVO: Adiciona o ícone da janela ---
        try:
            self.launcher._set_dialog_icon(self)
        except Exception as e:
            print(f"Aviso: Não foi possível aplicar ícone à janela de mods: {e}")
        # --- FIM DA NOVIDADE ---
        
        # --- Múltiplos diretórios (Sem mudanças) ---
        self.mods_dir = os.path.join(MODPACKS_DIR, modpack_name, "mods")
        self.resourcepacks_dir = os.path.join(MODPACKS_DIR, modpack_name, "resourcepacks")
        self.shaderpacks_dir = os.path.join(MODPACKS_DIR, modpack_name, "shaderpacks")
        
        os.makedirs(self.mods_dir, exist_ok=True)
        os.makedirs(self.resourcepacks_dir, exist_ok=True)
        os.makedirs(self.shaderpacks_dir, exist_ok=True)
        
        # --- LÓGICA DE DETECÇÃO (Sem mudanças) ---
        self.game_version = ""
        self.loader = ""
        try:
            version_id = modpack_config.get("version", "")
            if not version_id:
                raise Exception("Modpack não tem versão definida.")
                
            if "fabric" in version_id.lower():
                self.loader = "fabric"
            elif "neoforge" in version_id.lower():
                self.loader = "neoforge"
            elif "forge" in version_id.lower():
                self.loader = "forge"
            else:
                self.loader = "forge" 

            version_json_path = os.path.join(VERSIONS_DIR, version_id, f"{version_id}.json")
            if not os.path.exists(version_json_path):
                base_version = version_id.split('-')[0]
                if not base_version:
                     raise Exception(f"Arquivo {version_id}.json não encontrado!")
                self.game_version = base_version
            else:
                with open(version_json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                base_version = data.get("inheritsFrom")
                if base_version:
                    self.game_version = base_version
                else:
                    self.game_version = version_id
                
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível determinar a versão do modpack: {e}", parent=self)
            self.destroy()
            return
        
        # --- Referências de UI (Sem mudanças) ---
        self.default_mod_icon = None
        self.mod_icons = {} 
        self.selected_project_id = None
        self.selected_frame = None
        
        self.current_offset = 0
        self.hits_per_page = 20 
        
        self.current_project_type = "mod"
        
        # --- MUDANÇA: Fallback do Ícone Padrão ---
        try:
            img = Image.open(os.path.join(BASE_DIR, "default_pack.png")).resize((64, 64), Image.Resampling.LANCZOS)
            self.default_mod_icon = ImageTk.PhotoImage(img)
        except Exception as e:
            print(f"[AVISO] 'default_pack.png' não encontrado para o ModDownloader. Usando fallback. Erro: {e}")
            # Cria um quadrado cinza escuro (visível no tema) em vez de transparente
            img = Image.new('RGBA', (64, 64), (60, 60, 60)) 
            self.default_mod_icon = ImageTk.PhotoImage(img)
        # --- FIM DA MUDANÇA ---

        # --- Constrói a UI (Plano B - Combobox) ---
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill="both", expand=True)
        
        top_frame = ttk.Frame(main_frame)
        top_frame.pack(fill="x", pady=(0, 5))
        top_frame.columnconfigure(1, weight=1) 

        ttk.Label(top_frame, text="Categoria:").grid(row=0, column=0, sticky="w", padx=(0, 10))
        
        self.category_combo = ttk.Combobox(
            top_frame,
            state="readonly",
            values=["Mods", "Resource Packs", "Shaders"],
            width=20 
        )
        self.category_combo.grid(row=1, column=0, sticky="w", padx=(0, 10))
        self.category_combo.set("Mods")
        
        self.category_combo.bind("<<ComboboxSelected>>", self.on_category_changed)
        
        ttk.Label(top_frame, text="Buscar:").grid(row=0, column=1, sticky="w", padx=(10, 0))
        
        self.search_entry = ttk.Entry(top_frame)
        self.search_entry.grid(row=1, column=1, sticky="ew", padx=(10, 10))
        
        self.search_button = ttk.Button(top_frame, text="Buscar", command=lambda: self.start_search_thread(offset_change=0))
        self.search_button.grid(row=1, column=2, sticky="e")
        
        self.search_entry.bind("<Return>", lambda e: self.start_search_thread(offset_change=0))
        
        # --- Meio: Lista de Mods Rolável (Sem mudanças) ---
        scroll_frame = ttk.Frame(main_frame)
        scroll_frame.pack(fill="both", expand=True, pady=(10, 0))
        scroll_frame.rowconfigure(0, weight=1)
        scroll_frame.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(scroll_frame, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(scroll_frame, orient="vertical", command=self.canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.list_frame = ttk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.list_frame, anchor="nw")

        self.list_frame.bind("<Configure>", self._on_frame_configure)
        self._bind_mousewheel(self) 
        self._bind_mousewheel(self.canvas) 
        self._bind_mousewheel(self.list_frame) 

        # --- Fundo: Botões e Status (Sem mudanças) ---
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill="x", pady=(10, 0))
        
        self.status_label = ttk.Label(bottom_frame, text=f"Buscando no Modrinth para {self.game_version}...")
        self.status_label.pack(side="left", fill="x", expand=True) 
        
        self.prev_page_button = ttk.Button(
            bottom_frame, text="< Anterior", state="disabled", 
            command=lambda: self.start_search_thread(offset_change=-self.hits_per_page)
        )
        self.prev_page_button.pack(side="left", padx=5)
        
        self.next_page_button = ttk.Button(
            bottom_frame, text="Próxima >", state="disabled", 
            command=lambda: self.start_search_thread(offset_change=self.hits_per_page)
        )
        self.next_page_button.pack(side="left", padx=5)
        
        self.download_button = ttk.Button(bottom_frame, text="Baixar Selecionado", bootstyle="success-outline", command=self.start_download_thread)
        self.download_button.pack(side="right")
        
        self.start_search_thread(offset_change=0)

    def on_category_changed(self, event=None):
        """Chamado quando uma categoria é selecionada no Combobox."""
        
        # 1. Pega o texto do combobox (ex: "Resource Packs")
        selected_category = self.category_combo.get()
        
        # 2. Traduz para o nome da API
        if selected_category == "Mods":
            self.current_project_type = "mod"
        elif selected_category == "Resource Packs":
            self.current_project_type = "resourcepack"
        elif selected_category == "Shaders":
            self.current_project_type = "shader" # Corrigido para "shader" (API do Modrinth)
        else:
            self.current_project_type = "mod" # Padrão
            
        print(f"[DEBUG] Categoria alterada para: {self.current_project_type}")
        
        # 3. Inicia uma nova busca (resetando para a página 1)
        self.start_search_thread(offset_change=0)

    # --- Funções Auxiliares para a Lista Rolável ---

    def _on_frame_configure(self, event=None):
        """Atualiza a região de rolagem do canvas."""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _bind_mousewheel(self, widget):
        """Aplica o bind de rolagem do mouse (cross-platform)."""
        widget.bind_all("<MouseWheel>", self._on_mousewheel_windows, add="+")
        widget.bind_all("<Button-4>", self._on_mousewheel_linux, add="+")
        widget.bind_all("<Button-5>", self._on_mousewheel_linux, add="+")

    def _on_mousewheel_windows(self, event):
        """Rolagem no Windows."""
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_mousewheel_linux(self, event):
        """Rolagem no Linux."""
        if event.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(1, "units")

    # --- Funções de UI Atualizadas ---

    def set_status(self, text, style=INFO):
        """Atualiza o label de status (thread-safe)."""
        try:
            self.status_label.config(text=text, bootstyle=style)
        except tk.TclError:
            pass # Janela foi fechada

    def _load_mod_icon(self, icon_label, icon_url):
        """(THREAD) Baixa o ícone de um mod e o exibe no label fornecido."""
        try:
            headers = {'User-Agent': f'RaposoLauncher/{self.launcher.LAUNCHER_VERSION}'}
            resp = requests.get(icon_url, headers=headers)
            resp.raise_for_status()
            
            img_data = BytesIO(resp.content)
            img = Image.open(img_data).resize((64, 64), Image.Resampling.LANCZOS)
            
            # Guarda a referência para o Tkinter não "perder" a imagem
            photo = ImageTk.PhotoImage(img)
            self.mod_icons[icon_url] = photo 
            
            # Agenda a atualização da imagem na thread da UI
            self.after(0, icon_label.config, {"image": photo})
            
        except Exception as e:
            # Se falhar, ele fica com o ícone padrão que já foi setado
            print(f"Erro ao carregar ícone {icon_url}: {e}")

    def on_mod_selected(self, event, project_id, frame):
        """Chamado quando um 'card' de mod é clicado."""
        
        # 1. Desmarca o card antigo (se houver)
        if self.selected_frame:
            try:
                self.selected_frame.config(bootstyle="secondary")
            except tk.TclError:
                pass # Frame já foi destruído (ex: em uma nova busca)

        # 2. Marca o card novo
        frame.config(bootstyle="primary") # Estilo de "selecionado"
        
        # 3. Salva a referência
        self.selected_frame = frame
        self.selected_project_id = project_id
        
        # Habilita o botão de download
        self.download_button.config(state="normal")
        
    def _create_mod_widget(self, mod_data):
        """Cria o 'card' de mod individual e o adiciona na lista."""
        
        project_id = mod_data.get("project_id")
        if not project_id:
            return

        # --- O 'Card' Principal ---
        # (Usamos 'secondary' para o fundo cinza-claro do tema 'cyborg')
        mod_frame = ttk.Frame(self.list_frame, padding=10, bootstyle="secondary")
        mod_frame.pack(fill="x", pady=(5, 0), padx=(5, 10)) # pady(5,0) para espaçar
        
        # Configura o grid do card
        mod_frame.columnconfigure(1, weight=1) # Coluna do meio (título/desc) estica
        
        # --- Coluna 0: Ícone ---
        icon_label = ttk.Label(mod_frame, image=self.default_mod_icon, bootstyle="secondary")
        icon_label.grid(row=0, column=0, rowspan=4, sticky="nw", padx=(0, 10))
        
        icon_url = mod_data.get("icon_url")
        if icon_url:
            threading.Thread(target=self._load_mod_icon, args=(icon_label, icon_url), daemon=True).start()
            
        # --- Coluna 1: Informações ---
        title = mod_data.get("title", "Mod Desconhecido")
        author = mod_data.get("author", "Autor Desconhecido")
        description = mod_data.get("description", "Sem descrição.")

        title_label = ttk.Label(mod_frame, text=title, font=("Helvetica", 12, "bold"), bootstyle="secondary-inverse")
        title_label.grid(row=0, column=1, sticky="w")
        
        author_label = ttk.Label(mod_frame, text=f"by {author}", bootstyle="secondary-inverse")
        author_label.grid(row=1, column=1, sticky="w")
        
        desc_label = ttk.Label(mod_frame, text=description, wraplength=450, justify="left", bootstyle="secondary-inverse")
        desc_label.grid(row=2, column=1, sticky="w", pady=(5, 0))

        # --- Coluna 2: Estatísticas ---
        stats_frame = ttk.Frame(mod_frame, bootstyle="secondary")
        stats_frame.grid(row=0, column=2, rowspan=4, sticky="ne", padx=(10, 0))
        
        downloads = mod_data.get("downloads", 0)
        followers = mod_data.get("follows", 0)
        
        ttk.Label(stats_frame, text=f"📥 {downloads:,} Downloads", bootstyle="secondary-inverse").pack(anchor="e")
        ttk.Label(stats_frame, text=f"⭐ {followers:,} Seguidores", bootstyle="secondary-inverse").pack(anchor="e")
        
        # --- Bind de Clique ---
        # Precisamos de um 'lambda' para passar os argumentos
        click_func = lambda e, p=project_id, f=mod_frame: self.on_mod_selected(e, p, f)
        
        # Binda o clique em todos os widgets do card
        mod_frame.bind("<Button-1>", click_func)
        for widget in mod_frame.winfo_children() + stats_frame.winfo_children():
            widget.bind("<Button-1>", click_func)

    def start_search_thread(self, event=None, offset_change=0):
        """Inicia o thread de busca, com suporte a offset."""
        query = self.search_entry.get().strip()
        
        # --- LÓGICA DE OFFSET ---
        if offset_change == 0:
            # Se é uma nova busca (offset_change=0), reseta o offset
            self.current_offset = 0
        else:
            # Se é mudança de página, calcula o novo offset
            self.current_offset += offset_change
        
        # Garante que o offset não seja negativo
        if self.current_offset < 0:
            self.current_offset = 0
        # --- FIM DA LÓGICA ---
            
        self.set_status(f"Buscando (Página {self.current_offset // self.hits_per_page + 1})...", INFO)
        
        # Desabilita TODOS os botões de navegação
        self.search_button.config(state="disabled")
        self.download_button.config(state="disabled") 
        self.next_page_button.config(state="disabled")
        self.prev_page_button.config(state="disabled")
        
        # Limpa o estado da seleção
        self.selected_project_id = None
        self.selected_frame = None
        
        # Limpa a lista de mods (destrói os frames antigos)
        for child in self.list_frame.winfo_children():
            child.destroy()
        
        # Reposiciona o scroll para o topo
        self.canvas.yview_moveto(0)
        
        threading.Thread(target=self._search_thread, args=(query, self.current_offset), daemon=True).start()

    def _search_thread(self, query, offset):
        """(THREAD) Busca na API do Modrinth, com suporte a offset E categoria."""
        try:
            # --- Lógica de Facets (CORRIGIDA) ---
            
            facets_list = [
                [f"project_type:{self.current_project_type}"]
            ]
            
            # --- CORREÇÃO AQUI ---
            # 1. Adiciona a versão do jogo APENAS se NÃO for shader
            if self.current_project_type != "shader": # Usando a sua correção
            # --- FIM DA CORREÇÃO ---
                facets_list.append([f"versions:{self.game_version}"])

            # 2. Adiciona o loader APENAS se for um mod
            if self.current_project_type == "mod":
                loaders = [self.loader]
                if self.loader == "forge":
                    loaders.append("neoforge")
                facets_list.append(["categories:" + l for l in loaders])
            
            facets = json.dumps(facets_list)
            
            if query:
                params = {"query": query, "facets": facets, "offset": offset, "limit": self.hits_per_page}
            else:
                params = {"sort": "downloads", "facets": facets, "offset": offset, "limit": self.hits_per_page}
            
            headers = {'User-Agent': f'RaposoLauncher/{self.launcher.LAUNCHER_VERSION}'}
            
            resp = requests.get("https://api.modrinth.com/v2/search", params=params, headers=headers)
            resp.raise_for_status()
            
            data = resp.json()
            hits = data.get("hits", []) 
            
            def _populate_mod_list():
                if not hits:
                    self.set_status("Nenhum item encontrado nesta página.", WARNING)
                    if self.current_offset > 0:
                        self.prev_page_button.config(state="normal")
                    return
                
                for mod_data in hits:
                    self._create_mod_widget(mod_data)
                
                self.set_status(f"Mostrando {len(hits)} itens (Página {self.current_offset // self.hits_per_page + 1}).", SUCCESS)

                if len(hits) == self.hits_per_page:
                    self.next_page_button.config(state="normal")
                
                if self.current_offset > 0:
                    self.prev_page_button.config(state="normal")

            self.after(0, _populate_mod_list) 
            
        except Exception as e:
            self.after(0, self.set_status, f"Erro na busca: {e}", DANGER)
        finally:
            self.after(0, self.search_button.config, {"state": "normal"})

    def start_download_thread(self):
        """Inicia o thread de download para o mod selecionado."""
        
        project_id = self.selected_project_id
        if not project_id: 
            return messagebox.showerror("Erro", "Selecione um mod na lista para baixar.", parent=self)
            
        self.set_status(f"Buscando versão para {project_id}...", INFO)
        self.download_button.config(state="disabled")
        
        threading.Thread(target=self._download_thread, args=(project_id,), daemon=True).start()
        
    def _download_thread(self, project_id):
        """(THREAD) Busca a versão correta e baixa para a pasta certa."""
        try:
            # 1. Busca as versões do projeto
            headers = {'User-Agent': f'RaposoLauncher/{self.launcher.LAUNCHER_VERSION}'}
            
            params = {}
            
            # --- CORREÇÃO AQUI ---
            # Adiciona a versão do jogo APENAS se NÃO for shader
            if self.current_project_type != "shader": # Usando a sua correção
            # --- FIM DA CORREÇÃO ---
                params["game_versions"] = json.dumps([self.game_version])
            
            # Adiciona o loader SÓ SE for um mod
            if self.current_project_type == "mod":
                 params["loaders"] = json.dumps([self.loader])
                 
            url = f"https://api.modrinth.com/v2/project/{project_id}/version"
            
            resp = requests.get(url, params=params, headers=headers)
            resp.raise_for_status()
            
            versions = resp.json()
            
            # Fallback (Apenas para mods)
            if not versions and self.current_project_type == "mod" and (self.loader == "neoforge" or self.loader == "forge"):
                print("Fallback: Tentando buscar por 'forge'...")
                params["loaders"] = json.dumps(["forge"])
                resp = requests.get(url, params=params, headers=headers)
                resp.raise_for_status()
                versions = resp.json()

            if not versions:
                raise Exception(f"Nenhuma versão compatível foi encontrada.")
            
            # 2. Pega a versão mais recente
            latest_version = versions[0]
            
            # 3. Pega o arquivo principal
            file_to_download = latest_version.get("files", [{}])[0]
            file_url = file_to_download.get("url")
            file_name = file_to_download.get("filename")
            
            if not file_url or not file_name:
                raise Exception("API retornou uma versão sem arquivo.")
            
            # --- CORREÇÃO AQUI ---
            target_dir = self.mods_dir 
            if self.current_project_type == "resourcepack":
                target_dir = self.resourcepacks_dir
                print(f"[DEBUG] Salvando Resource Pack em: {target_dir}")
            elif self.current_project_type == "shader": # Usando a sua correção
                target_dir = self.shaderpacks_dir
                print(f"[DEBUG] Salvando Shader em: {target_dir}")
            # --- FIM DA CORREÇÃO ---
            else:
                print(f"[DEBUG] Salvando Mod em: {target_dir}")

            # 4. Baixa o arquivo
            self.after(0, self.set_status, f"Baixando {file_name}...")
            
            file_path = os.path.join(target_dir, file_name)
            self.launcher.download_file(file_url, file_path, file_name) 
            
            self.after(0, self.set_status, f"✅ {file_name} baixado!", SUCCESS)

        except Exception as e:
            self.after(0, self.set_status, f"Erro ao baixar: {e}", DANGER)
        finally:
            self.after(0, self.download_button.config, {"state": "normal"})

# --- Funções de Ajuda ---
def offline_uuid_for(name: str) -> str:
    """Gera um UUID offline baseado no nome de usuário."""
    return str(uuid.uuid3(uuid.NAMESPACE_DNS, "OfflinePlayer:" + name))

# --- Classe Principal do Launcher ---
class RaposoLauncher(ttk.Window):
    def __init__(self):
        super().__init__(themename="cyborg")
        self.title("Raposo Launcher")
        self.geometry("950x600") 
        self.resizable(False, False)

        # --- LÓGICA DE ÍCONE ---
        self.icon_path = None # Padrão
        try:
            icon_path = os.path.join(BASE_DIR, "icon.ico")
            if os.path.exists(icon_path):
                self.iconbitmap(icon_path)
                self.icon_path = icon_path
            else:
                print("Aviso: Ficheiro 'icon.ico' não encontrado. Usando ícone padrão.")
        except Exception as e:
            print(f"Aviso: Não foi possível carregar o 'icon.ico'. {e}")

        self.selections = {}
        self.accounts = []
        self.active_account = None
        self.java_options = {}
        
        self.LAUNCHER_VERSION = "v4.4.5"
        self.logo_clicks = 0
        
        self.bg_photo = None
        self.bg_canvas = None
        self.logo_photo = None 
        
        self.modpack_icon_label = None 
        self.modpack_icon_photo = None 
        self.default_pack_icon = None
        
        self.progressbar = None    
        self.start_button = None   
        self.ui_queue = Queue()    
        
        # --- MUDANÇA: Inicializa as BooleanVars aqui ---
        self.show_terminal = tk.BooleanVar() 
        self.close_after_launch = tk.BooleanVar()
        # --- FIM DA MUDANÇA ---
        
        self.use_default_minecraft_dir = False # Padrão
        
        # --- LÓGICA DE JOGO/DISCORD ---
        self.discord_client_id = "1436820336816427213"
        self.RPC = None
        self.game_process = None
        self.discord_state = "No menu principal"
        self.discord_details = "Escolhendo um modpack..."
        self.discord_small_image = None 
        self.discord_small_text = "Raposo Launcher"
        
        threading.Thread(target=self._discord_rpc_thread, daemon=True).start()
        
        self.bind("<Destroy>", self._on_close)

        # --- MUDANÇA: Ordem de inicialização corrigida ---
        
        # 1. Carrega as configs (define self.use_default_minecraft_dir, etc.)
        # Esta função agora também ATUALIZA o settings.json se a chave faltar
        self.load_settings() 
        
        # 2. Define os caminhos de jogo com base nas configs
        self._update_paths()
        
        # 3. Constrói a UI
        self.build_ui()
        
        # 4. Carrega o resto (Java, Contas, Modpacks)
        self.load_javas()
        self.load_accounts()
        self.load_selections()
        
        # 5. Define o modpack salvo (agora que o combobox existe)
        self.load_last_modpack_selection()
        
        # 6. Inicia a fila da UI
        self.process_ui_queue()


    def build_ui(self):
        """Constrói a nova interface gráfica com a barra de progresso."""
        
        # 1. Carrega e desenha o fundo (Sem mudanças)
        self.load_background()

        # 2. Carrega e desenha o Logo (Sem mudanças)
        try:
            logo_path = os.path.join(BASE_DIR, "logo.jpg")
            logo_img_raw = Image.open(logo_path)
            
            max_width = 400
            if logo_img_raw.width > max_width:
                w_percent = (max_width / float(logo_img_raw.width))
                h_size = int((float(logo_img_raw.height) * float(w_percent)))
                logo_img = logo_img_raw.resize((max_width, h_size), Image.Resampling.LANCZOS)
            else:
                logo_img = logo_img_raw
            
            self.logo_photo = ImageTk.PhotoImage(logo_img)
            
            logo_canvas_item = self.bg_canvas.create_image(
                250, 60, image=self.logo_photo, anchor="n" 
            )
            
            self.bg_canvas.tag_bind(logo_canvas_item, '<Button-1>', self.on_logo_click)
            
        except FileNotFoundError:
            print("AVISO: Imagem 'logo.jpg' não encontrada. Pulando o título.")
        except Exception as e:
            print(f"Erro ao carregar logo.jpg: {e}")

        # --- INÍCIO DA CORREÇÃO (Voltamos ao .place() original) ---

        # 3. Cria o Frame lateral para os controles
        # O PAI é 'self' para herdar o tema
        controls_frame = ttk.Frame(self, padding=25, bootstyle="dark")
        # Usamos .place() com a altura original
        controls_frame.place(
            x=500, y=100,  
            width=420, height=310 
        )
        
        controls_frame.grid_propagate(False) 
        
        controls_frame.columnconfigure(0, weight=0, minsize=58) 
        controls_frame.columnconfigure(1, weight=1)

        # (Linha 0: Conta)
        ttk.Label(controls_frame, text="Conta:", font=("Helvetica", 11)).grid(row=0, column=0, sticky="w", pady=10, padx=(0, 10))
        self.accounts_combo = ttk.Combobox(controls_frame, state="readonly") 
        self.accounts_combo.grid(row=0, column=1, sticky="ew", pady=10, padx=(10, 0)) 
        self.accounts_combo.bind("<<ComboboxSelected>>", self.on_account_selected)

        # (Linha 1: Ícone do Modpack)
        try:
            default_icon_path = os.path.join(BASE_DIR, "default_pack.png")
            img = Image.open(default_icon_path).resize((48, 48), Image.Resampling.LANCZOS)
            self.default_pack_icon = ImageTk.PhotoImage(img)
        except Exception as e:
            print(f"Aviso: 'default_pack.png' não encontrado. {e}")
            img = Image.new('RGBA', (48, 48), (0,0,0,0))
            self.default_pack_icon = ImageTk.PhotoImage(img)
        
        self.modpack_icon_label = ttk.Label(controls_frame, image=self.default_pack_icon)
        self.modpack_icon_label.grid(row=1, column=0, sticky="w", pady=10, padx=(0, 10))

        # (Linha 1: Modpack Combobox)
        self.selection_combo = ttk.Combobox(controls_frame, state="readonly", font=("Helvetica", 11)) 
        self.selection_combo.grid(row=1, column=1, sticky="ew", pady=10, padx=(10, 0))
        self.selection_combo.bind("<<ComboboxSelected>>", self.on_modpack_selected)

        # (Linha 2: Checkboxes)
        check_frame = ttk.Frame(controls_frame)
        check_frame.grid(row=2, column=0, columnspan=2, sticky="w", pady=(10,0), padx=0)

        self.close_after_launch = tk.BooleanVar()
        check = ttk.Checkbutton(check_frame, text="Fechar launcher ao iniciar", variable=self.close_after_launch, command=self.on_checkbox_toggled)
        check.pack(side="left") 

        check_terminal = ttk.Checkbutton(check_frame, text="Iniciar com terminal", variable=self.show_terminal, command=self.on_checkbox_toggled)
        check_terminal.pack(side="left", padx=(15, 0)) 
        
        # (Linha 3: Barra de Botões) 
        button_frame = ttk.Frame(controls_frame)
        button_frame.grid(row=3, column=0, columnspan=2, pady=(20, 10), sticky="ew")
        
        button_frame.columnconfigure((0, 1, 2), weight=1)
        
        # Fileiras 1, 2, 3... (Tudo igual)
        ttk.Button(button_frame, text="🔧 Ger. Contas", bootstyle="info-outline", command=self.manage_accounts).grid(row=0, column=0, sticky="ew", padx=2, pady=2)
        ttk.Button(button_frame, text="➕ Novo", bootstyle="info-outline", command=self.criar_modpack).grid(row=0, column=1, sticky="ew", padx=2, pady=2)
        ttk.Button(button_frame, text="✏️ Editar", bootstyle="warning-outline", command=self.editar_modpack).grid(row=0, column=2, sticky="ew", padx=2, pady=2)
        ttk.Button(button_frame, text="📂 Abrir Pasta", bootstyle="secondary-outline", command=self.abrir_pasta_modpack).grid(row=1, column=0, sticky="ew", padx=2, pady=2)
        ttk.Button(button_frame, text="📥 Importar", bootstyle="primary-outline", command=self.importar_modpack).grid(row=1, column=1, sticky="ew", padx=2, pady=2)
        ttk.Button(button_frame, text="📤 Exportar", bootstyle="primary-outline", command=self.exportar_modpack).grid(row=1, column=2, sticky="ew", padx=2, pady=2)
        
        # --- MUDANÇA AQUI ---
        ttk.Button(
            button_frame, 
            text="📚 Biblioteca Modrinth", # <- Texto alterado
            bootstyle="success-outline", 
            command=self.open_mod_downloader
        ).grid(row=2, column=0, columnspan=3, sticky="ew", padx=2, pady=2)
        # --- FIM DA MUDANÇA ---
        
        # --- FIM DO CONTROLS_FRAME ---

        # 4. Cria o Botão START
        self.start_button = ttk.Button(
            self, 
            text="🚀 START", 
            bootstyle="success-outline", 
            command=self.on_start_button_click 
        )
        # MUDANÇA DE 'Y': 420 (era 395). (y=100 + height=310 + 10px de espaço)
        self.start_button.place(x=500, y=420, width=420, height=50)

        # 5. Cria a Barra de Progresso
        self.progressbar = ttk.Progressbar(
            self, 
            mode="determinate", 
            bootstyle="success-striped"
        )
        # MUDANÇA DE 'Y': 480 (era 455). (y=420 + height=50 + 10px de espaço)
        self.progressbar.place(x=500, y=480, width=420, height=20)
        
        # 6. Cria o Label de Status
        self.status_label = ttk.Label(self, text="", font=("Helvetica", 11))
        # MUDANÇA DE 'Y': 510 (era 485). (y=480 + height=20 + 10px de espaço)
        # (x=710 é 500 + 420/2, está centralizado)
        self.status_label.place(x=710, y=510, anchor="center") 

        # --- FIM DA CORREÇÃO ---

        # 7. Copyrights (Sem mudanças)
        subtle_color = self.style.colors.get("secondary") 
        self.bg_canvas.create_text(
            940, 575, text="Raposo Launcher (2025) © Raposo", 
            font=("Helvetica", 9), fill=subtle_color, anchor="se" 
        )
        self.bg_canvas.create_text(
            940, 590, text="Minecraft © Mojang AB.",
            font=("Helvetica", 9), fill=subtle_color, anchor="se" 
        )
        
        self.bg_canvas.create_text(
            10, 590, text=self.LAUNCHER_VERSION, 
            font=("Helvetica", 9), fill=subtle_color, anchor="sw" 
        )

    def _discord_rpc_thread(self):
        """(THREAD) Controla a conexão e atualização do Discord Rich Presence."""
        
        # Tenta se conectar
        try:
            self.RPC = pypresence.Presence(self.discord_client_id)
            self.RPC.connect() 
            print("[Discord RPC] Conectado ao Discord.")
        except Exception as e:
            print(f"[Discord RPC] Erro ao conectar: {e}")
            print("[Discord RPC] (O Discord está aberto?)")
            return # Encerra o thread se não conseguir conectar

        # <--- CORREÇÃO AQUI ---
        # Define o tempo de início UMA VEZ, fora do loop
        start_time = int(time.time())
        # <--- FIM DA CORREÇÃO ---

        # Loop de atualização (a cada 15 segundos)
        while True:
            try:
                # --- GRANDES MUDANÇAS AQUI ---
                self.RPC.update(
                    state=self.discord_state,
                    details=self.discord_details,
                    large_image="logo",    # O logo principal
                    large_text=f"Raposo Launcher {self.LAUNCHER_VERSION}",
                    small_image=self.discord_small_image, # A IMAGEM DINÂMICA
                    small_text=self.discord_small_text,   # O TEXTO DINÂMICO
                    start=start_time,
                    
                    # --- BOTÕES (COLOQUE SEUS LINKS) ---
                    buttons=[
                        {"label": "Baixar o Raposo Launcher", "url": "https://github.com/assuerogames/RaposoLauncher"},
                        {"label": "Entrar no Discord", "url": "https://discord.gg/SEU-CONVITE"} # Troque pelo seu link
                    ]
                    # --- FIM DAS MUDANÇAS ---
                )
            except Exception as e:
                # Se o Discord fechar ou der erro, encerra o loop
                print(f"[Discord RPC] Erro ao atualizar: {e}")
                try:
                    self.RPC.close()
                except:
                    pass
                return # Encerra o thread
                
            time.sleep(15) # Espera 15 segundos (padrão do Discord)

    def _on_close(self, event=None):
        """Chamado quando a janela principal é fechada."""
        
        # <--- ADIÇÃO AQUI ---
        # Tenta "matar" o processo do jogo se ele estiver rodando
        if self.game_process:
            try:
                print("[DEBUG] Fechando o launcher e o jogo...")
                self.game_process.kill()
            except Exception as e:
                print(f"Não foi possível fechar o jogo: {e}")
        # <--- FIM DA ADIÇÃO ---
            
        try:
            if self.RPC:
                self.RPC.close()
                print("[Discord RPC] Desconectado.")
        except Exception as e:
            print(f"[Discord RPC] Erro ao fechar: {e}")

    def _wait_for_game_close_thread(self, game_process):
        """(THREAD) Espera o processo do jogo terminar."""
        try:
            # Esta linha "trava" ESTE thread até o jogo fechar
            game_process.wait()
            
            # O jogo fechou, envia a mensagem para a UI
            print("[DEBUG] Jogo fechado. Solicitando reabertura do launcher...")
            self.ui_queue.put({"type": "show_launcher"})
            
        except Exception as e:
            print(f"Erro ao esperar pelo jogo: {e}")
        finally:
            # Limpa a referência
            self.game_process = None

    def _show_easter_egg(self):
        """Cria a janela do Easter Egg."""
        dialog = tk.Toplevel(self)
        dialog.title("🦊✨")
        dialog.geometry("350x180") 
        dialog.resizable(False, False)
        dialog.grab_set() # Trava o foco nesta janela
        
        # Aplica o ícone que já definimos antes
        self._set_dialog_icon(dialog) 

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame, 
            text="Tu encontraste o Easter Egg da Raposa!", 
            font=("Helvetica", 12, "bold")
        ).pack(pady=5) # Menos pady
        
        ttk.Label(
            frame, 
            text="Feito com ❤️ e ☕ por Raposo!"
        ).pack(pady=5)

        ttk.Label(
            frame, 
            # Puxamos a versão da variável da classe
            text=f"Versão do Launcher: {self.LAUNCHER_VERSION}", 
            bootstyle="secondary"
        ).pack(pady=(10, 5))


        ttk.Button(
            frame, 
            text="Fantástico!", 
            command=dialog.destroy, 
            bootstyle="success-outline"
        ).pack(pady=10) # Menos pady

    def on_logo_click(self, event=None):
        """Chamado quando o logo no canvas é clicado."""
        self.logo_clicks += 1
        print(f"[DEBUG] Logo clicado {self.logo_clicks}/10 vezes.") # Feedback no terminal
        
        if self.logo_clicks >= 10:
            print("[DEBUG] Easter Egg ativado!")
            self._show_easter_egg()
            self.logo_clicks = 0 # Repõe o contador

    def _set_dialog_icon(self, dialog):
        """Aplica o ícone do launcher a uma janela Toplevel (diálogo)."""
        # self.icon_path é definido no __init__
        if self.icon_path:
            try:
                dialog.iconbitmap(self.icon_path)
            except Exception as e:
                # Evita que um ícone corrompido quebre as janelas secundárias
                print(f"Aviso: Não foi possível aplicar ícone à janela secundária. {e}")

    def load_background(self):
        """Carrega e exibe a imagem de fundo, cortando-a para caber sem distorção."""
        # A importação da PIL foi movida para o topo do script
        
        try:
            img_path = os.path.join(BASE_DIR, "background.png")
            img = Image.open(img_path)
            
            img = ImageOps.fit(img, (950, 600), Image.Resampling.LANCZOS) 
            
            self.bg_photo = ImageTk.PhotoImage(img)
            
            self.bg_canvas = tk.Canvas(self, width=950, height=600, highlightthickness=0) 
            self.bg_canvas.place(x=0, y=0, relwidth=1, relheight=1)
            
            self.bg_canvas.create_image(0, 0, image=self.bg_photo, anchor="nw")
            
        except FileNotFoundError:
            print("AVISO: Imagem 'background.png' não encontrada. Usando fundo sólido.")
            self.bg_canvas = tk.Canvas(self, width=950, height=600, bg="#2b3e50", highlightthickness=0)
            self.bg_canvas.place(x=0, y=0, relwidth=1, relheight=1)
        except Exception as e:
            messagebox.showerror("Erro ao Carregar Imagem", f"Ocorreu um erro: {e}")

    def open_mod_downloader(self):
        """Abre a janela de download de mods."""
        
        # 1. Pega o modpack selecionado
        modpack_name = self.selection_combo.get().strip()
        if not modpack_name:
            return messagebox.showerror("Erro", "Selecione um modpack primeiro!")
        
        # 2. Pega a config desse modpack
        config = self.load_modpack_config(modpack_name)
        version_str = config.get("version")
        
        if not version_str:
             return messagebox.showerror("Erro", "O modpack selecionado não tem uma versão definida!")

        # 3. Abre a nova janela
        ModDownloader(self, self, modpack_name, config)

    # ---------------------------
    # Java
    # ---------------------------
    def load_javas(self):
        """Carrega as instalações Java encontradas na pasta 'java' e a do sistema."""
        options = {"Java do Sistema": "java"}
        if os.path.exists(JAVA_ROOT):
            for folder in sorted(os.listdir(JAVA_ROOT)):
                folder_path = os.path.join(JAVA_ROOT, folder)
                if os.path.isdir(folder_path):
                    exe_name = "java.exe" if os.name == "nt" else "java"
                    candidate = os.path.join(folder_path, "bin", exe_name)
                    if os.path.exists(candidate) and os.access(candidate, os.X_OK):
                        options[folder] = candidate
        self.java_options = options
        names = list(options.keys())
        try:
            self.java_combo["values"] = names
            # Tenta definir java8 como padrão, senão usa a primeira opção
            default = "java8" if "java8" in options else names[0] if names else ""
            if default: self.java_combo.set(default)
        except Exception:
            pass # Pode falhar se a UI estiver sendo destruída

    def get_selected_java(self, java_name: str) -> str:
        """Pega um nome de java (ex: 'java17') e retorna o caminho completo do executável."""
        # Se o nome não estiver nas opções carregadas (ex: 'Java do Sistema'),
        # apenas retorna o nome (que será "java")
        if java_name not in self.java_options:
            return java_name
        
        return self.java_options.get(java_name, "java")

    # ---------------------------
    # Accounts
    # ---------------------------
    def load_accounts(self):
        """Carrega as contas do arquivo accounts.json."""
        if not os.path.exists(ACCOUNTS_FILE):
            self._create_default_account()
            return
        try:
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            self._create_default_account()
            return

        accounts_dict = data.get("accounts", {})
        self.active_account = data.get("activeAccount")
        self.accounts = [{"id": k, "name": v.get("username", "Desconhecido"), "uuid": v.get("uuid"), "type": v.get("type","offline")} for k,v in accounts_dict.items()]
        
        # Garante que a conta ativa existe
        if not self.active_account or self.active_account not in accounts_dict:
            if self.accounts: 
                self.active_account = self.accounts[0]["id"]
                self.save_accounts()
        self._refresh_accounts_ui()

    def _create_default_account(self):
        """Cria um arquivo de contas padrão com um 'Player' offline."""
        default_name = "Player"
        default_uuid = offline_uuid_for(default_name)
        acc_id = f"offline-{default_uuid}"
        data = {"accounts": {acc_id: {"username": default_name, "uuid": default_uuid, "type": "offline"}}, "activeAccount": acc_id}
        with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self.active_account = acc_id
        self.accounts = [{"id": acc_id, "name": default_name, "uuid": default_uuid, "type": "offline"}]
        self._refresh_accounts_ui()

    def save_accounts(self):
        """Salva a lista de contas atual e a conta ativa no JSON."""
        data = {"accounts": {}, "activeAccount": self.active_account}
        for acc in self.accounts:
            data["accounts"][acc["id"]] = {"username": acc["name"], "uuid": acc["uuid"], "type": acc["type"]}
        try: 
            with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f: 
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            messagebox.showerror("Erro", f"Falha ao salvar contas: {e}")

    def _refresh_accounts_ui(self):
        """Atualiza o combobox de contas com a lista de contas."""
        names = [f"{a['name']} ({a['type']})" for a in self.accounts]
        self.accounts_combo["values"] = names
        if self.accounts:
            active = next((a for a in self.accounts if a["id"] == self.active_account), None)
            self.accounts_combo.set(f"{active['name']} ({active['type']})" if active else names[0])
        else: 
            self.accounts_combo.set("")

    def on_account_selected(self, event=None):
        """Chamado quando uma nova conta é selecionada. Salva a seleção."""
        sel = self.accounts_combo.get().split(" (")[0] # Pega o nome
        for a in self.accounts:
            if a["name"] == sel:
                self.active_account = a["id"]
                self.save_accounts()
                break

    def manage_accounts(self):
        """Abre uma janela (AGORA COM TTKBOOTSTRAP) para criar e deletar contas offline."""
        dialog = tk.Toplevel(self)
        dialog.title("Gerenciar Contas")
        dialog.geometry("450x380") # Um pouco mais alto para a nova lista
        dialog.resizable(False, False)
        dialog.grab_set() 
        
        self._set_dialog_icon(dialog)

        # Frame principal
        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill="both", expand=True)

        # --- Seção da Lista de Contas ---
        ttk.Label(frame, text="Contas Salvas:", font=("Helvetica", 11, "bold")).pack(pady=(0, 10))

        # Criar o Treeview (nova lista)
        tv_frame = ttk.Frame(frame)
        tv_frame.pack(fill="x", expand=True)
        
        # Colunas
        account_tv = ttk.Treeview(tv_frame, columns=("nome", "tipo"), show="headings", height=6)
        account_tv.heading("nome", text="Nome de Usuário")
        account_tv.heading("tipo", text="Tipo")
        account_tv.column("nome", width=250)
        account_tv.column("tipo", width=100)
        
        # Scrollbar (se a lista for grande)
        scrollbar = ttk.Scrollbar(tv_frame, orient="vertical", command=account_tv.yview)
        account_tv.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side="right", fill="y")
        account_tv.pack(side="left", fill="x", expand=True)

        # Preenche a lista
        def refresh_list():
            """Limpa e preenche o Treeview com as contas atuais."""
            # Limpa itens antigos
            for item in account_tv.get_children():
                account_tv.delete(item)
            
            # Adiciona itens novos
            for acc in self.accounts:
                # Salva o ID da conta no 'iid' (identificador interno)
                account_tv.insert("", "end", iid=acc["id"], values=(acc["name"], acc["type"]))
        
        refresh_list() # Chama pela primeira vez

        # --- Seção de Criar Conta ---
        ttk.Separator(frame).pack(fill="x", pady=15)
        ttk.Label(frame, text="Criar conta offline:", font=("Helvetica", 11, "bold")).pack(pady=(5, 10))
        
        create_frame = ttk.Frame(frame)
        create_frame.pack(fill="x")
        
        new_name_entry = ttk.Entry(create_frame, bootstyle="secondary")
        new_name_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        # --- Funções dos Botões (Adaptadas para o Treeview) ---
        
        def create_offline():
            nm = new_name_entry.get().strip()
            if not nm: 
                return messagebox.showerror("Erro","Digite um nome", parent=dialog)
            if any(a["name"].lower() == nm.lower() for a in self.accounts): 
                return messagebox.showerror("Erro","Conta já existe", parent=dialog)
            
            new_uuid = offline_uuid_for(nm)
            acc_id = f"offline-{new_uuid}"
            new_acc = {"id": acc_id, "name": nm, "uuid": new_uuid, "type": "offline"}
            
            self.accounts.append(new_acc)
            self.active_account = acc_id
            self.save_accounts()
            self._refresh_accounts_ui() # Atualiza o menu principal
            
            # Atualiza a lista nesta janela
            account_tv.insert("", "end", iid=new_acc["id"], values=(new_acc["name"], new_acc["type"]))
            new_name_entry.delete(0,"end")

        def delete_selected():
            # Pega o item selecionado no Treeview
            sel = account_tv.selection()
            if not sel: 
                return messagebox.showerror("Erro","Selecione uma conta na lista", parent=dialog)
            
            account_id_to_delete = sel[0] # O 'iid' que salvamos
            
            # Encontra a conta na nossa lista self.accounts
            account = next((a for a in self.accounts if a["id"] == account_id_to_delete), None)
            if not account:
                return # Segurança, caso algo dê errado
            
            if not messagebox.askyesno("Confirmar", f"Deletar conta '{account['name']}'?", parent=dialog): 
                return
            
            # Remove da lista self.accounts
            self.accounts.remove(account)
            
            # Define a conta ativa como a primeira, se houver, ou None
            self.active_account = self.accounts[0]["id"] if self.accounts else None
            
            self.save_accounts()
            self._refresh_accounts_ui() # Atualiza o menu principal
            
            # Remove da lista nesta janela
            account_tv.delete(account_id_to_delete)

        # Botão de Criar
        create_btn = ttk.Button(
            create_frame, 
            text="Criar", 
            bootstyle="success-outline", 
            command=create_offline
        )
        create_btn.pack(side="right")

        # Botão de Deletar
        delete_btn = ttk.Button(
            frame, 
            text="Deletar Conta Selecionada", 
            bootstyle="danger-outline", 
            command=delete_selected
        )
        delete_btn.pack(pady=(15, 0), fill="x")

    # ---------------------------
    # Selections (Versões / Modpacks)
    # ---------------------------
    def load_selections(self):
        """Carrega APENAS os modpacks da pasta 'modpacks'."""
        self.selections.clear()
        options = []
        
        os.makedirs(MODPACKS_DIR, exist_ok=True)
        
        for modpack_name in sorted(os.listdir(MODPACKS_DIR)):
            if os.path.isdir(os.path.join(MODPACKS_DIR, modpack_name)):
                label = modpack_name 
                self.selections[label] = ("modpack", modpack_name)
                options.append(label)
                
        if not options: 
            # Define uma versão padrão (a última da lista)
            versions = sorted([v for v in os.listdir(VERSIONS_DIR) if os.path.isdir(os.path.join(VERSIONS_DIR,v))])
            default_version = versions[-1] if versions else "NENHUMA"
            
            # Cria o config padrão
            self.save_modpack_config("Default", {
                "version": default_version,
                "java": "java17" if "1.17" in default_version or "1.18" in default_version or "1.19" in default_version or "1.20" in default_version else "java8",
                "ram": "4G"
            })
            label = "Default"
            self.selections[label] = ("modpack", "Default")
            options.append(label)
            
        self.selection_combo["values"] = options
        # NÃO definimos mais o .set() aqui. O load_settings vai fazer isso.

    def _ensure_vanilla_json_exists(self, version_id):
        """
        (SINCRONO) Garante que o .json de uma versão vanilla exista.
        Se não existir, baixa-o. Se não encontrar, lança um erro.
        Esta função é feita para ser chamada de dentro de um thread.
        """
        path = os.path.join(VERSIONS_DIR, version_id, f"{version_id}.json")
        
        # 1. Se já existir, não faz nada
        if os.path.exists(path):
            print(f"[DEBUG Vanilla] Base {version_id}.json já existe.")
            return True
            
        # 2. Se não existir, baixa
        print(f"[DEBUG Vanilla] Arquivo {version_id}.json não encontrado. Baixando...")
        
        # 2a. Busca o "cardápio" principal da Mojang
        manifest_url = "https://launchermeta.mojang.com/mc/game/version_manifest.json"
        manifest_resp = requests.get(manifest_url)
        manifest_resp.raise_for_status()
        manifest_data = manifest_resp.json()
        
        # 2b. Encontra a URL para a versão específica
        target_url = next((v["url"] for v in manifest_data["versions"] if v["id"] == version_id), None)
        
        if not target_url:
            # Se não encontrar (ex: versão não existe), lança um erro claro
            raise FileNotFoundError(f"Versão '{version_id}' não foi encontrada no manifest da Mojang.")
            
        # 2c. Baixa o arquivo .json
        print(f"[DEBUG Vanilla] Baixando {version_id}.json de {target_url}")
        self.download_file(target_url, path, f"{version_id}.json")
        print(f"[DEBUG Vanilla] {version_id}.json baixado com sucesso.")
        return True

    def _version_key(self, v_str):
        """
        Cria uma chave de ordenação numérica para versões (ex: 1.12.2 > 1.9.4).
        Usa RegEx para extrair o primeiro padrão "X.Y.Z".
        """
        # Tenta encontrar o primeiro padrão de versão (ex: "1.12.2")
        match = re.search(r'(\d+)\.(\d+)(?:\.(\d+))?', v_str)
        
        if match:
            # Se achar, converte os números para uma tupla de inteiros
            # ex: "1.12.2" -> (1, 12, 2)
            # ex: "1.9" -> (1, 9, 0)
            parts = match.groups()
            return tuple(int(p) if p is not None else 0 for p in parts)
        
        # Se não encontrar nenhum padrão (ex: "fabric-loader...", "a1.0.16"), 
        # retorna uma chave "muito baixa" para que eles fiquem no final.
        return (0, 0, 0)

    def _get_pretty_version_name(self, real_name):
        """
        Converte um nome de pasta de versão (ex: 1.12.2-forge...) 
        em um nome legível (ex: 1.12.2 (Forge 47.1.3)).
        
        AGORA LÊ O JSON PARA DESCOBRIR A VERSÃO BASE DO MC.
        """
        name_low = real_name.lower()
        
        # --- NOVO: Tentar ler o JSON para a versão base ---
        mc_version = ""
        version_json_path = os.path.join(VERSIONS_DIR, real_name, f"{real_name}.json")
        
        if os.path.exists(version_json_path):
            try:
                with open(version_json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # A versão base do MC está em 'inheritsFrom'
                mc_version = data.get("inheritsFrom")
                if not mc_version:
                    # Se não herda, é a própria versão (ex: vanilla 1.20.1)
                    mc_version = data.get("id", real_name)
                    
            except Exception as e:
                print(f"[AVISO] Não foi possível ler {real_name}.json: {e}")
        # --- FIM DA NOVA LÓGICA ---

        try:
            # --- NeoForge ---
            if "neoforge" in name_low:
                # O nome do MC *deve* ter sido encontrado no JSON
                if mc_version:
                    # Extrai a versão do NeoForge do *nome da pasta*
                    loader_version = real_name.replace('neoforge-', '') # ex: "20.4.251"
                    return f"{mc_version} (NeoForge {loader_version})"
                else:
                    # Fallback se o JSON falhou (lógica antiga)
                    parts = real_name.split('-') # ex: [1.20.4, neoforge, 20.4.251]
                    if len(parts) >= 3 and parts[1] == 'neoforge':
                        return f"{parts[0]} (NeoForge {parts[2]})"

            # --- Forge ---
            if "forge" in name_low:
                if mc_version:
                    # Tenta extrair a versão do Forge do nome da pasta
                    parts = real_name.split('-') # ex: [1.12.2, forge, 14.23.5.2860]
                    if len(parts) >= 3 and parts[1] == 'forge':
                        return f"{mc_version} (Forge {parts[2]})"
                # Fallback (lógica antiga)
                parts = real_name.split('-') 
                if len(parts) >= 3 and parts[1] == 'forge':
                    return f"{parts[0]} (Forge {parts[2]})"
            
            # --- Fabric ---
            if "fabric-loader" in name_low:
                if mc_version:
                    parts = real_name.split('-') # ex: [fabric, loader, 0.15.11, 1.20.1]
                    if len(parts) >= 4 and parts[0] == 'fabric' and parts[1] == 'loader':
                        return f"{mc_version} (Fabric {parts[2]})" # mc_version do JSON é mais confiável
                # Fallback (lógica antiga)
                parts = real_name.split('-')
                if len(parts) >= 4 and parts[0] == 'fabric' and parts[1] == 'loader':
                    return f"{parts[3]} (Fabric {parts[2]})"
            
            # --- OptiFine ---
            if "optifine" in name_low:
                if mc_version:
                    parts = real_name.split('-') # ex: [1.12.2, OptiFine_HD_U_G5]
                    if len(parts) >= 2:
                        loader_name = parts[1].replace('OptiFine_', '')
                        return f"{mc_version} (OptiFine {loader_name})"
                # Fallback (lógica antiga)
                parts = real_name.split('-')
                if len(parts) >= 2:
                    loader_name = parts[1].replace('OptiFine_', '')
                    return f"{parts[0]} (OptiFine {loader_name})"

            # --- Vanilla, Snapshot, Alpha/Beta ---
            # Se mc_version foi encontrado, ele é a 'real_name' (ex: 1.20.1, 24w10a)
            display_name = mc_version if mc_version and mc_version == real_name else real_name
            
            category = self._classify_version(real_name)
            
            if category == "vanilla":
                return f"{display_name} (Vanilla)"
            if category == "snapshots":
                return f"{display_name} (Snapshot)"
            
            # --- CORREÇÃO AQUI ---
            if category == "alpha_beta":
                # A 'display_name' já é o nome real (ex: 'a1.2.6')
                if display_name.startswith('a'):
                    return f"{display_name} (Alpha)"
                if display_name.startswith('b'):
                    return f"{display_name} (Beta)"
                if 'infdev' in name_low:
                    return f"{display_name} (Infdev)"
                if 'c0.' in name_low:
                    return f"{display_name} (Classic)"
                return f"{display_name} (Alpha/Beta)" # Fallback
            # --- FIM DA CORREÇÃO ---
            
            # --- Outros / Fallback ---
            if category == "outros":
                return f"{real_name} (Outros)"
                
        except Exception as e:
            print(f"[AVISO] Falha ao traduzir nome '{real_name}': {e}")
            pass 
            
        # Fallback final se tudo der errado
        return real_name

    def _classify_version(self, real_name):
        """Classifica um nome de versão em uma categoria (ex: 'forge', 'vanilla', 'snapshots')."""
        name_low = real_name.lower()
        
        # 1. Loaders
        if "neoforge" in name_low: 
            return "neoforge"
        if "forge" in name_low: 
            return "forge"
        if "fabric" in name_low: 
            return "fabric"
        if "optifine" in name_low: 
            return "optifine"
        
        # 2. Tipos Históricos
        if 'snapshot' in name_low or re.search(r'^\d+w\d+[a-z]?', name_low): 
            return "snapshots"
        
        # --- CORREÇÃO AQUI ---
        # Checa por 'a' ou 'b' seguido de um número (ex: a1.2.6, b1.8.1)
        # Ou checa pelos nomes 'infdev' e 'c0.' (classic)
        if 'infdev' in name_low or 'c0.' in name_low or \
           re.search(r'^[ab](\d+)', name_low):
            return "alpha_beta"
        # --- FIM DA CORREÇÃO ---
            
        # 3. Vanilla (Release, Pre-Release, RC)
        if re.fullmatch(r'(\d+)\.(\d+)(?:\.(\d+))?(?:-(?:pre|rc)\d+)?', real_name):
            return "vanilla"
            
        # 4. Fallback (se ainda tiver um número, provavelmente é vanilla)
        if re.search(r'(\d+)\.(\d+)', real_name):
            return "vanilla"
            
        # 5. Se não for nada disso
        return "outros"

    def open_version_downloader(self, parent_dialog, version_combo):
        """Abre uma nova janela para baixar manifestos de versão da Mojang."""
        
        downloader_dialog = tk.Toplevel(parent_dialog)
        downloader_dialog.title("Baixar Versões")
        downloader_dialog.geometry("300x520") 
        downloader_dialog.resizable(False, False)
        downloader_dialog.grab_set() 

        self._set_dialog_icon(downloader_dialog)

        # --- ESTRUTURA DE ABAS (NOTEBOOK) ---
        notebook = ttk.Notebook(downloader_dialog)
        notebook.pack(fill="both", expand=True, pady=10, padx=10)
        
        # --- Aba 1: Vanilla ---
        vanilla_tab_frame = ttk.Frame(notebook, padding=(5, 10))
        notebook.add(vanilla_tab_frame, text="Vanilla")
        
        # --- Aba 2: Fabric ---
        fabric_tab_frame = ttk.Frame(notebook, padding=(5, 10))
        notebook.add(fabric_tab_frame, text="Fabric")

        # --- Aba 3: Forge ---
        forge_tab_frame = ttk.Frame(notebook, padding=(5, 10))
        notebook.add(forge_tab_frame, text="Forge")

        # --- Aba 4: OptiFine (Era Quilt) ---
        optifine_tab_frame = ttk.Frame(notebook, padding=(5, 10))
        notebook.add(optifine_tab_frame, text="OptiFine")

        # --- Aba 5: NeoForge (REMOVIDA) ---
        
        
        # --- ###################### ---
        # --- SEÇÃO DA ABA VANILLA ---
        # --- ###################### ---
        
        self.show_snapshot = tk.BooleanVar(value=False)
        self.show_alpha_beta = tk.BooleanVar(value=False)
        filter_frame = ttk.Frame(vanilla_tab_frame) 
        filter_frame.pack(pady=5, fill="x", padx=10)
        version_urls = {}
        search_frame = ttk.Frame(vanilla_tab_frame) 
        search_frame.pack(fill="x", padx=10, pady=(0, 5))
        ttk.Label(search_frame, text="Buscar:").pack(side="left", padx=(5, 5))
        search_entry = ttk.Entry(search_frame)
        search_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        def update_listbox_view(event=None):
            search_term = search_entry.get().lower()
            version_listbox.delete(0, "end") 
            available_versions = list(version_urls.keys())
            for v_id in available_versions:
                if not search_term or search_term in v_id.lower():
                    version_listbox.insert("end", v_id)
            on_version_select(None)
        
        def fetch_versions():
            try:
                status_label.config(text="Buscando versões...", bootstyle=INFO)
                download_button.config(state="disabled") 
                search_entry.config(state="disabled")
                cb_snapshot.config(state="disabled")
                cb_alpha_beta.config(state="disabled")
                version_urls.clear()
                manifest_url = "https://launchermeta.mojang.com/mc/game/version_manifest.json"
                manifest_resp = requests.get(manifest_url)
                manifest_resp.raise_for_status()
                manifest_data = manifest_resp.json()
                local_versions = [v for v in os.listdir(VERSIONS_DIR) if os.path.isdir(os.path.join(VERSIONS_DIR,v))]
                include_snapshot = self.show_snapshot.get()
                include_alpha_beta = self.show_alpha_beta.get()
                allowed_types = ["release"]
                if include_snapshot: allowed_types.append("snapshot")
                if include_alpha_beta: allowed_types.extend(["old_alpha", "old_beta"])
                for v_entry in manifest_data.get("versions", []):
                    v_id = v_entry.get("id")
                    v_type = v_entry.get("type")
                    if v_type in allowed_types and v_id not in local_versions:
                        version_urls[v_id] = v_entry.get("url")
                status_label.config(text="Selecione uma versão para baixar:")
            except Exception as e:
                status_label.config(text=f"Erro ao buscar: {e}", bootstyle=DANGER)
            finally:
                search_entry.config(state="normal")
                cb_snapshot.config(state="normal")
                cb_alpha_beta.config(state="normal")
                downloader_dialog.after(0, update_listbox_view)

        cb_snapshot = ttk.Checkbutton(
            filter_frame, text="Mostrar Snapshots", variable=self.show_snapshot,
            command=lambda: threading.Thread(target=fetch_versions, daemon=True).start()
        )
        cb_snapshot.pack(side="left", padx=(10, 5))
        cb_alpha_beta = ttk.Checkbutton(
            filter_frame, text="Mostrar Alphas/Betas", variable=self.show_alpha_beta,
            command=lambda: threading.Thread(target=fetch_versions, daemon=True).start()
        )
        cb_alpha_beta.pack(side="left", padx=5)
        status_label = ttk.Label(vanilla_tab_frame, text="Buscando versões da Mojang...") 
        status_label.pack(pady=10)
        list_frame = ttk.Frame(vanilla_tab_frame) 
        list_frame.pack(fill="both", expand=True, padx=10)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        version_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, height=15)
        scrollbar.config(command=version_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        version_listbox.pack(side="left", fill="both", expand=True)
        download_button = ttk.Button(vanilla_tab_frame, text="Baixar Versão Selecionada", state="disabled") 
        download_button.pack(pady=10)
        search_entry.bind("<KeyRelease>", update_listbox_view)

        def on_version_select(event):
            if version_listbox.curselection():
                download_button.config(state="normal")
            else:
                download_button.config(state="disabled")

        version_listbox.bind("<<ListboxSelect>>", on_version_select)

        def do_download():
            try:
                selected_index = version_listbox.curselection()
                if not selected_index: return
                version_id = version_listbox.get(selected_index)
                status_label.config(text=f"Baixando {version_id}.json...")
                download_button.config(state="disabled")
                search_entry.config(state="disabled")
                cb_snapshot.config(state="disabled")
                cb_alpha_beta.config(state="disabled")
                target_url = version_urls.get(version_id)
                if not target_url: raise Exception(f"URL para {version_id} não encontrada.")
                version_path = os.path.join(VERSIONS_DIR, version_id)
                version_json_path = os.path.join(version_path, f"{version_id}.json")
                self.download_file(target_url, version_json_path, f"{version_id}.json")
                status_label.config(text=f"{version_id}.json baixado!", bootstyle=SUCCESS)
                new_versions = sorted([v for v in os.listdir(VERSIONS_DIR) if os.path.isdir(os.path.join(VERSIONS_DIR,v))])
                version_combo["values"] = new_versions
                version_combo.set(version_id)
                downloader_dialog.destroy()
            except Exception as e:
                status_label.config(text=f"Erro no download: {e}", bootstyle=DANGER)
                download_button.config(state="normal")
                search_entry.config(state="normal")
                cb_snapshot.config(state="normal")
                cb_alpha_beta.config(state="normal")

        download_button.config(command=do_download)
        threading.Thread(target=fetch_versions, daemon=True).start()
        
        # --- FIM DA SEÇÃO DA ABA VANILLA ---


        # --- ##################### ---
        # --- SEÇÃO DA ABA FABRIC ---
        # --- ##################### ---
        
        fabric_loader_versions = [] 
        fabric_ui_frame = ttk.Frame(fabric_tab_frame)
        fabric_ui_frame.pack(fill="x", padx=10, pady=5)
        fabric_ui_frame.columnconfigure(1, weight=1)
        ttk.Label(fabric_ui_frame, text="Versão do Jogo:").grid(row=0, column=0, sticky="w", pady=5)
        fabric_mc_combo = ttk.Combobox(fabric_ui_frame, state="readonly", values=["Buscando..."])
        fabric_mc_combo.grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=5)
        fabric_mc_combo.set("Buscando...")
        ttk.Label(fabric_ui_frame, text="Versão do Loader:").grid(row=1, column=0, sticky="w", pady=5)
        fabric_loader_combo = ttk.Combobox(fabric_ui_frame, state="disabled", values=["Selecione o jogo..."])
        fabric_loader_combo.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=5)
        fabric_loader_combo.set("Selecione o jogo...")
        fabric_install_button = ttk.Button(
            fabric_tab_frame, 
            text="Instalar Fabric", 
            state="disabled",
            bootstyle="success-outline"
        )
        fabric_install_button.pack(pady=20)
        fabric_status_label = ttk.Label(fabric_tab_frame, text="Selecione a versão do Minecraft.")
        fabric_status_label.pack(pady=10, fill="x")

        def _handle_fabric_install_success(version_id):
            fabric_status_label.config(text=f"{version_id} instalado!", bootstyle=SUCCESS)
            new_versions = sorted([v for v in os.listdir(VERSIONS_DIR) if os.path.isdir(os.path.join(VERSIONS_DIR,v))])
            version_combo["values"] = new_versions
            version_combo.set(version_id) 
            downloader_dialog.destroy()

        def _handle_fabric_install_failure(error_msg):
            fabric_status_label.config(text=f"Erro: {error_msg}", bootstyle=DANGER)
            try:
                fabric_mc_combo.config(state="readonly")
                fabric_loader_combo.config(state="readonly")
                fabric_install_button.config(state="normal")
            except tk.TclError:
                pass 

        def do_fabric_install():
            try:
                mc_version = fabric_mc_combo.get()
                loader_version = fabric_loader_combo.get()
                if not mc_version or not loader_version:
                    raise Exception("Versão não selecionada.")
                
                try:
                    fabric_status_label.config(text=f"Checando base {mc_version} (vanilla)...")
                    self._ensure_vanilla_json_exists(mc_version)
                except Exception as e:
                    raise Exception(f"Falha ao baixar base {mc_version}: {e}")

                fabric_status_label.config(text="Buscando perfil de instalação...")
                url = f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}/{loader_version}/profile/json"
                resp = requests.get(url)
                resp.raise_for_status()
                data = resp.json()
                version_id = data.get("id")
                if not version_id:
                    raise Exception("JSON de perfil inválido, 'id' não encontrado.")
                version_path = os.path.join(VERSIONS_DIR, version_id)
                version_json_path = os.path.join(version_path, f"{version_id}.json")
                fabric_status_label.config(text=f"Salvando {version_id}.json...")
                os.makedirs(version_path, exist_ok=True)
                with open(version_json_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                downloader_dialog.after(0, _handle_fabric_install_success, version_id)
            except Exception as e:
                downloader_dialog.after(0, _handle_fabric_install_failure, str(e))

        def on_install_fabric_click():
            fabric_mc_combo.config(state="disabled")
            fabric_loader_combo.config(state="disabled")
            fabric_install_button.config(state="disabled")
            fabric_status_label.config(text="Iniciando instalação...", bootstyle=INFO)
            threading.Thread(target=do_fabric_install, daemon=True).start()
        
        fabric_install_button.config(command=on_install_fabric_click)

        def _populate_loader_combobox(versions):
            nonlocal fabric_loader_versions
            if not isinstance(versions, list):
                fabric_status_label.config(text="Erro: Resposta inesperada da API.", bootstyle=DANGER)
                return
            fabric_loader_versions = versions
            all_loaders = [
                v['loader']['version'] 
                for v in versions 
                if isinstance(v, dict) and v.get('loader') and v['loader'].get('version')
            ]
            if all_loaders:
                fabric_loader_combo.config(values=all_loaders)
                fabric_loader_combo.set(all_loaders[0]) 
                fabric_status_label.config(text="Selecione a versão do loader.")
                fabric_install_button.config(state="normal")
            else:
                fabric_loader_combo.config(values=["Nenhum loader encontrado"], state="disabled")
                fabric_loader_combo.set("Nenhum loader encontrado")
                fabric_status_label.config(text="Nenhum loader encontrado para esta versão.", bootstyle=WARNING)
            fabric_loader_combo.config(state="readonly")

        def fetch_fabric_loader_versions(mc_version):
            try:
                url = f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}"
                resp = requests.get(url)
                resp.raise_for_status()
                data = resp.json()
                downloader_dialog.after(0, _populate_loader_combobox, data)
            except Exception as e:
                downloader_dialog.after(0, fabric_status_label.config, {"text": f"Erro ao buscar loaders: {e}", "bootstyle": DANGER})

        def on_fabric_mc_selected(event):
            mc_version = fabric_mc_combo.get()
            if not mc_version or "Buscando" in mc_version or "Selecione" in mc_version:
                return
            fabric_loader_combo.config(state="disabled", values=["Buscando loaders..."])
            fabric_loader_combo.set("Buscando loaders...")
            fabric_install_button.config(state="disabled")
            fabric_status_label.config(text=f"Buscando loaders para {mc_version}...", bootstyle=INFO)
            threading.Thread(target=fetch_fabric_loader_versions, args=(mc_version,), daemon=True).start()
        
        fabric_mc_combo.bind("<<ComboboxSelected>>", on_fabric_mc_selected)

        def _populate_mc_combobox(versions):
            stable_versions = [v["version"] for v in versions if v.get("stable", True)]
            fabric_mc_combo.config(values=stable_versions)
            fabric_mc_combo.set("Selecione uma versão...")
            fabric_mc_combo.config(state="readonly")
            fabric_status_label.config(text="Selecione uma versão do jogo.")

        def fetch_fabric_mc_versions():
            try:
                url = "https://meta.fabricmc.net/v2/versions/game"
                resp = requests.get(url)
                resp.raise_for_status()
                data = resp.json()
                downloader_dialog.after(0, _populate_mc_combobox, data)
            except Exception as e:
                downloader_dialog.after(0, fabric_status_label.config, {"text": f"Erro ao buscar versões: {e}", "bootstyle": DANGER})
        
        threading.Thread(target=fetch_fabric_mc_versions, daemon=True).start()

        # --- FIM DA SEÇÃO DA ABA FABRIC ---


        # --- ################################# ---
        # --- SEÇÃO DA ABA FORGE (AUTOMÁTICA) ---
        # --- ################################# ---
        
        self.forge_version_data = [] 
        self.forge_loader_details = {} 

        forge_ui_frame = ttk.Frame(forge_tab_frame)
        forge_ui_frame.pack(fill="x", padx=10, pady=5)
        forge_ui_frame.columnconfigure(1, weight=1)

        ttk.Label(forge_ui_frame, text="Versão do Jogo:").grid(row=0, column=0, sticky="w", pady=5)
        forge_mc_combo = ttk.Combobox(forge_ui_frame, state="readonly", values=["Buscando..."])
        forge_mc_combo.grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=5)
        forge_mc_combo.set("Buscando...")

        ttk.Label(forge_ui_frame, text="Versão do Forge:").grid(row=1, column=0, sticky="w", pady=5)
        forge_loader_combo = ttk.Combobox(forge_ui_frame, state="disabled", values=["Selecione o jogo..."])
        forge_loader_combo.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=5)
        forge_loader_combo.set("Selecione o jogo...")

        forge_refresh_btn = ttk.Button(
            forge_tab_frame,
            text="Concluído! Atualizar e Fechar",
            bootstyle="success-outline"
        )

        forge_install_button = ttk.Button(
            forge_tab_frame, 
            text="Instalar Forge", 
            state="disabled",
            bootstyle="success-outline"
        )
        forge_install_button.pack(pady=20)

        forge_status_label = ttk.Label(forge_tab_frame, text="Selecione a versão do Minecraft.")
        forge_status_label.pack(pady=10, fill="x")


        def _on_forge_gui_complete(jar_path, jar_name):
            """Chamado pelo botão 'Concluído' da GUI."""
            try:
                if jar_path and os.path.exists(jar_path):
                    os.remove(jar_path)
                    print(f"[DEBUG Forge] Limpeza GUI: {jar_path} removido.")
                
                log_path = os.path.join(BASE_DIR, jar_name + ".log")
                if jar_name and os.path.exists(log_path):
                    os.remove(log_path)
                    print(f"[DEBUG Forge] Limpeza GUI: {log_path} removido.")
            except Exception as e:
                 print(f"[AVISO Forge] Falha ao limpar arquivos de instalação GUI: {e}")
            finally:
                new_versions = sorted([v for v in os.listdir(VERSIONS_DIR) if os.path.isdir(os.path.join(VERSIONS_DIR,v))])
                version_combo["values"] = new_versions
                forge_versions = [v for v in new_versions if "forge" in v.lower()]
                if forge_versions:
                    version_combo.set(forge_versions[-1])
                downloader_dialog.destroy()

        def _handle_forge_install_success(is_gui=False, jar_path=None, jar_name=None):
            """(UI Thread) Chamado quando a instalação termina."""
            if is_gui:
                forge_status_label.config(text="Instalador GUI aberto. Siga os passos e clique em 'Concluído'.", bootstyle=INFO)
                forge_install_button.pack_forget() 
                
                forge_refresh_btn.config(command=lambda: _on_forge_gui_complete(jar_path, jar_name))
                forge_refresh_btn.pack(pady=20) 
            else:
                forge_status_label.config(text="Forge instalado com sucesso!", bootstyle=SUCCESS)
                
                new_versions = sorted([v for v in os.listdir(VERSIONS_DIR) if os.path.isdir(os.path.join(VERSIONS_DIR,v))])
                version_combo["values"] = new_versions
                
                forge_versions = [v for v in new_versions if "forge" in v.lower()]
                if forge_versions:
                    version_combo.set(forge_versions[-1])
                
                downloader_dialog.after(2000, downloader_dialog.destroy)


        def _handle_forge_install_failure(error_message):
            """(UI Thread) Chamado se a instalação silenciosa falhar."""
            print(f"[ERRO FORGE] {error_message}")
            forge_status_label.config(text="Erro na instalação. Verifique o terminal.", bootstyle=DANGER)
            
            try:
                forge_mc_combo.config(state="readonly")
                forge_loader_combo.config(state="readonly")
                forge_install_button.config(state="normal")
            except tk.TclError:
                pass 

        def do_forge_install():
            jar_path = None 
            jar_name = None
            is_gui_install = False 
            
            try:
                mc_version_base = forge_mc_combo.get() 
                loader_label = forge_loader_combo.get() 
                
                if not mc_version_base or "Buscando" in mc_version_base or "Selecione" in loader_label:
                    raise Exception("Seleção inválida.")
                    
                forge_version_id = self.forge_loader_details.get(loader_label)
                if not forge_version_id:
                    raise Exception("Erro ao encontrar dados do loader. Tente novamente.")

                # 1. Garante que o Vanilla .json exista
                forge_status_label.config(text=f"Checando base {mc_version_base} (vanilla)...")
                try:
                    self._ensure_vanilla_json_exists(mc_version_base)
                except Exception as e:
                    raise Exception(f"Falha ao baixar base {mc_version_base}: {e}")

                # 2. Baixar o instalador
                
                # <--- CORREÇÃO AQUI (Formato do Nome) ---
                # O formato do nome é SEMPRE o mesmo.
                jar_name = f"forge-{mc_version_base}-{forge_version_id}-installer.jar"
                # <--- FIM DA CORREÇÃO ---
                
                url = f"https://maven.minecraftforge.net/net/minecraftforge/forge/{mc_version_base}-{forge_version_id}/{jar_name}"
                
                temp_dir = os.path.join(GAME_DIR, "temp_installers")
                os.makedirs(temp_dir, exist_ok=True)
                jar_path = os.path.join(temp_dir, jar_name)

                forge_status_label.config(text=f"Baixando {jar_name}...")
                self.download_file(url, jar_path, jar_name)
                
                java_exec = self.get_selected_java("Java do Sistema")
                
                version_tuple = self._version_key(mc_version_base)
                
                if version_tuple >= (1, 13): 
                    forge_status_label.config(text="Instalando silenciosamente (Moderno)...", bootstyle=INFO)
                    
                    main_class = "net.minecraftforge.installer.SimpleInstaller" 
                    try:
                        with zipfile.ZipFile(jar_path, 'r') as zf:
                            with zf.open('META-INF/MANIFEST.MF') as mf:
                                for line in mf.read().decode('utf-8').splitlines():
                                    if line.startswith('Main-Class:'):
                                        main_class = line.split(':', 1)[1].strip()
                                        break
                    except Exception as e:
                        print(f"[AVISO FORGE] Não foi possível ler o MANIFEST.MF. {e}")

                    command = [java_exec, "-cp", jar_path, main_class, "--installClient"]
                    print(f"[DEBUG Forge] Executando: {' '.join(command)}")

                    creation_flags = 0
                    if platform.system().lower() == "windows":
                        creation_flags = 0x08000000 
                    
                    process = subprocess.Popen(
                        command, 
                        cwd=GAME_DIR, 
                        stdout=subprocess.PIPE, 
                        stderr=subprocess.PIPE, 
                        universal_newlines=True,
                        encoding='utf-8',
                        creationflags=creation_flags
                    )
                    
                    stdout, stderr = process.communicate()
                    
                    if process.returncode != 0:
                        raise Exception(stderr or stdout)
                    
                    print(f"[DEBUG Forge] Saída: {stdout}")
                    downloader_dialog.after(0, _handle_forge_install_success, False, None, None) 

                else: 
                    is_gui_install = True 
                    forge_status_label.config(text="Abrindo instalador (Antigo)...", bootstyle=INFO)
                    command = [java_exec, "-jar", jar_path]
                    print(f"[DEBUG Forge] Executando GUI: {' '.join(command)}")
                    
                    subprocess.Popen(command) 
                    
                    downloader_dialog.after(0, _handle_forge_install_success, True, jar_path, jar_name) 
                
            except Exception as e:
                downloader_dialog.after(0, _handle_forge_install_failure, str(e))
            
            finally:
                # 4. Limpar os arquivos
                try:
                    if not is_gui_install:
                        if jar_path and os.path.exists(jar_path):
                            os.remove(jar_path)
                            print(f"[DEBUG Forge] Limpeza: {jar_path} removido.")
                        
                        if jar_name:
                            log_path = os.path.join(GAME_DIR, jar_name + ".log")
                            if os.path.exists(log_path):
                                os.remove(log_path)
                                print(f"[DEBUG Forge] Limpeza: {log_path} removido.")
                except Exception as e:
                    print(f"[AVISO Forge] Falha ao limpar arquivos de instalação: {e}")


        def on_install_forge_click():
            """(UI) Chamado quando o botão de instalar é clicado."""
            forge_mc_combo.config(state="disabled")
            forge_loader_combo.config(state="disabled")
            forge_install_button.config(state="disabled")
            forge_status_label.config(text="Iniciando instalação...", bootstyle=INFO)
            
            threading.Thread(target=do_forge_install, daemon=True).start()
        
        forge_install_button.config(command=on_install_forge_click)

        def _populate_forge_loader_combobox(mc_version):
            """(UI) Preenche a combobox de loaders do Forge."""
            try:
                self.forge_loader_details.clear()
                labels = []
                
                loaders_for_mc = []
                for entry in self.forge_version_data:
                    requires_list = entry.get("requires", [{}])
                    mc_ver = ""
                    if requires_list and requires_list[0].get("uid") == "net.minecraft":
                        mc_ver = requires_list[0].get("equals")

                    if mc_ver == mc_version:
                        loaders_for_mc.append(entry)

                if not loaders_for_mc:
                    raise Exception("Nenhuma versão encontrada.")

                for entry in loaders_for_mc:
                    loader_version_id = entry.get("version")
                    if not loader_version_id:
                        continue
                        
                    label = loader_version_id
                    if entry.get("recommended"):
                        label += " (Recomendado)"
                    
                    elif entry.get("latest") and not any(e.g.get("recommended") for e in loaders_for_mc if isinstance(e, dict)): # Garante que 'e' é um dict
                         label += " (Mais Recente)"
                    
                    self.forge_loader_details[label] = loader_version_id 
                    labels.append(label)
                
                labels.sort(key=lambda x: " (Recomendado)" not in x)

                if labels:
                    forge_loader_combo.config(values=labels)
                    forge_loader_combo.set(labels[0]) 
                    forge_status_label.config(text="Selecione a versão do Forge.")
                    forge_install_button.config(state="normal")
                else:
                    raise Exception("Nenhuma versão encontrada.")

            except Exception as e:
                forge_loader_combo.config(values=["Nenhum loader encontrado"], state="disabled")
                forge_loader_combo.set("Nenhum loader encontrado")
                forge_status_label.config(text=f"Nenhum loader encontrado para {mc_version}.", bootstyle=WARNING)
            
            forge_loader_combo.config(state="readonly")


        def on_forge_mc_selected(event):
            """(UI) Chamado quando uma versão do MC é selecionada."""
            mc_version = forge_mc_combo.get()
            if not mc_version or "Buscando" in mc_version or "Selecione" in mc_version:
                return

            forge_loader_combo.config(state="disabled", values=["Buscando loaders..."])
            forge_loader_combo.set("Buscando loaders...")
            forge_install_button.config(state="disabled")
            forge_status_label.config(text=f"Buscando loaders para {mc_version}...", bootstyle=INFO)
            
            _populate_forge_loader_combobox(mc_version)


        def _populate_forge_mc_combobox(data):
            """(UI) Preenche a combobox de versões do MC."""
            
            def version_key(v_str):
                """Cria uma chave de ordenação numérica para versões (ex: 1.12.2 > 1.9.4)."""
                parts = v_str.split('-')[0] 
                try:
                    return tuple(int(p) for p in parts.split('.'))
                except ValueError:
                    return (0,) 
            
            try:
                self.forge_version_data = data.get("versions", [])
                if not self.forge_version_data:
                    raise Exception("JSON de versões do Forge está vazio.")
                
                mc_versions_set = set()
                for entry in self.forge_version_data:
                    requires_list = entry.get("requires", [{}])
                    if requires_list and requires_list[0].get("uid") == "net.minecraft":
                        mc_ver = requires_list[0].get("equals")
                        
                        # <--- CORREÇÃO AQUI (O FILTRO) ---
                        # Se a versão for 1.7.10 ou mais nova, adiciona
                        if mc_ver and version_key(mc_ver) >= (1, 7, 10):
                            mc_versions_set.add(mc_ver)
                        # <--- FIM DA CORREÇÃO ---

                
                mc_versions = sorted(list(mc_versions_set), key=version_key, reverse=True)
                
                if not mc_versions:
                    raise Exception("Nenhuma versão do MC encontrada no JSON.")

                forge_mc_combo.config(values=mc_versions)
                forge_mc_combo.set("Selecione uma versão...")
                forge_mc_combo.config(state="readonly")
                forge_status_label.config(text="Selecione uma versão do jogo.")
            except Exception as e:
                forge_status_label.config(text=f"Erro ao ler versões: {e}", bootstyle=DANGER)


        def fetch_forge_mc_versions():
            """(THREAD) Busca o JSON de mapeamento do Forge."""
            try:
                url = "https://meta.prismlauncher.org/v1/net.minecraftforge/index.json"
                resp = requests.get(url)
                resp.raise_for_status()
                data = resp.json()
                
                downloader_dialog.after(0, _populate_forge_mc_combobox, data)
            except Exception as e:
                downloader_dialog.after(0, forge_status_label.config, {"text": f"Erro ao buscar versões: {e}", "bootstyle": DANGER})

        forge_mc_combo.bind("<<ComboboxSelected>>", on_forge_mc_selected)
        threading.Thread(target=fetch_forge_mc_versions, daemon=True).start()

        # --- FIM DA SEÇÃO DA ABA FORGE ---


        # --- ######################## ---
        # --- SEÇÃO DA ABA OPTIFINE ---
        # --- ######################## ---
        
        optifine_status_label = ttk.Label(optifine_tab_frame, text="O OptiFine deve ser instalado manualmente.", justify="center", wraplength=250)
        optifine_status_label.pack(pady=10)

        def on_open_optifine_site():
            webbrowser.open("https://optifine.net/downloads")
            optifine_status_label.config(text="Site aberto. Baixe o arquivo .jar desejado.")

        def on_refresh_versions_and_close():
            optifine_status_label.config(text="Atualizando lista de versões...", bootstyle=INFO)
            
            new_versions = sorted([v for v in os.listdir(VERSIONS_DIR) if os.path.isdir(os.path.join(VERSIONS_DIR,v))])
            version_combo["values"] = new_versions
            
            optifine_versions = [v for v in new_versions if "optifine" in v.lower()]
            if optifine_versions:
                version_combo.set(optifine_versions[-1])
            
            downloader_dialog.destroy()

        def on_run_optifine_installer():
            try:
                jar_path = filedialog.askopenfilename(
                    title="Selecione o .jar do OptiFine",
                    filetypes=[("Arquivos Jar", "*.jar")],
                    parent=downloader_dialog
                )
                
                if not jar_path:
                    optifine_status_label.config(text="Instalação cancelada.")
                    return
                
                java_exec = self.get_selected_java("Java do Sistema")
                
                command = [java_exec, "-jar", jar_path]
                
                subprocess.Popen(command)
                
                optifine_status_label.config(text="Instalador aberto! Siga os passos nele e clique em 'Concluí'.", bootstyle=INFO)
                
                optifine_run_btn.pack_forget()
                optifine_refresh_btn.pack(pady=(10, 5), fill="x", padx=10)

            except Exception as e:
                optifine_status_label.config(text=f"Erro ao abrir instalador: {e}", bootstyle=DANGER)

        optifine_site_btn = ttk.Button(
            optifine_tab_frame,
            text="1. Abrir Site de Downloads",
            command=on_open_optifine_site,
            bootstyle="info-outline"
        )
        optifine_site_btn.pack(pady=(15, 5), fill="x", padx=10)
        
        optifine_run_btn = ttk.Button(
            optifine_tab_frame,
            text="2. Executar Instalador .jar",
            command=on_run_optifine_installer,
            bootstyle="primary-outline"
        )
        optifine_run_btn.pack(pady=(10, 5), fill="x", padx=10)
        
        optifine_refresh_btn = ttk.Button(
            optifine_tab_frame,
            text="3. Concluído! Atualizar e Fechar",
            command=on_refresh_versions_and_close,
            bootstyle="success-outline"
        )
        
        # --- FIM DA SEÇÃO DA ABA OPTIFINE ---


        # --- ################################### ---
        # --- SEÇÃO DE PLACEHOLDERS (REMOVIDA) ---
        # --- ################################### ---
        
        # (O código da aba NeoForge foi removido)
        
        # --- FIM DA SEÇÃO DE PLACEHOLDERS ---

    def criar_modpack(self): 
        self._modpack_dialog()
        
    def editar_modpack(self):
        modpacks = [m for m in os.listdir(MODPACKS_DIR) if os.path.isdir(os.path.join(MODPACKS_DIR,m))]
        if not modpacks: 
            return messagebox.showerror("Erro","Não há modpacks para editar!")
        self._modpack_dialog(edit=True, modpacks=modpacks)

    def _modpack_dialog(self, edit=False, modpacks=None):
        """Abre uma janela para criar ou editar um modpack (agora com filtro de versão)."""
        dialog = tk.Toplevel(self)
        dialog.title("Editar Modpack" if edit else "Novo Modpack")
        # Mais alto para o novo filtro
        dialog.geometry("400x400") 
        dialog.resizable(False, False)
        dialog.grab_set()

        self._set_dialog_icon(dialog)

        frame = ttk.Frame(dialog, padding=15)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1) 

        current_config = {}
        default_java = "java8"
        default_ram = "4G"

        # --- Nome do Modpack ---
        ttk.Label(frame, text="Nome do Modpack:", font=("Helvetica", 11)).grid(row=0, column=0, sticky="w", pady=6)
        if edit:
            modpack_name = self.selection_combo.get()
            if modpack_name not in modpacks:
                 modpack_name = modpacks[0]
                 
            name_combo = ttk.Combobox(frame, values=modpacks, state="readonly")
            name_combo.set(modpack_name)
            name_combo.grid(row=0, column=1, columnspan=2, sticky="ew", pady=6, padx=(10, 0))
            current_config = self.load_modpack_config(modpack_name)
        else: 
            name_entry = ttk.Entry(frame)
            name_entry.grid(row=0, column=1, columnspan=2, sticky="ew", pady=6, padx=(10, 0))
            
        
        # --- Listas de Versões (Lógica de Classificação) ---
        
        # 1. Pega todos os nomes reais e classifica
        real_versions_list = [v for v in os.listdir(VERSIONS_DIR) if os.path.isdir(os.path.join(VERSIONS_DIR,v))]
        real_versions_sorted = sorted(real_versions_list, key=self._version_key, reverse=True)

        # 2. Cria o "banco de dados" de versões
        #    all_versions_classified = { "vanilla": [ ("1.20.1 (Vanilla)", "1.20.1"), ("1.19.4", "1.19.4") ],
        #                                "forge":   [ ("1.12.2 (Forge)", "1.12.2-forge...") ] }
        all_versions_classified = {
            "todos": [], "vanilla": [], "neoforge": [], "forge": [], 
            "fabric": [], "optifine": [], "snapshots": [], "alpha_beta": [], "outros": []
        }
        
        # Usaremos isso para o 'confirmar'
        dialog.version_mapping = {}

        for real_name in real_versions_sorted:
            category = self._classify_version(real_name)
            pretty_name = self._get_pretty_version_name(real_name)
            
            # Lida com nomes bonitos duplicados (ex: dois "1.20.1 (Forge)")
            display_name = pretty_name
            count = 2
            while display_name in dialog.version_mapping:
                display_name = f"{pretty_name} ({count})"
                count += 1
            
            dialog.version_mapping[display_name] = real_name
            version_tuple = (display_name, real_name)
            
            all_versions_classified[category].append(version_tuple)
            all_versions_classified["todos"].append(version_tuple)

        
        # --- NOVO: Filtro de Versão ---
        ttk.Label(frame, text="Filtro:", font=("Helvetica", 11)).grid(row=1, column=0, sticky="w", pady=(6,0))
        
        filter_categories_map = {
            "Todos": "todos",
            "Vanilla": "vanilla",
            "NeoForge": "neoforge",
            "Forge": "forge",
            "Fabric": "fabric",
            "OptiFine": "optifine",
            "Snapshots": "snapshots",
            "Alpha/Beta": "alpha_beta",
            "Outros": "outros"
        }
        
        filter_combo = ttk.Combobox(frame, values=list(filter_categories_map.keys()), state="readonly")
        filter_combo.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(6,0), padx=(10, 0))
        
        
        # --- Versão (Agora controlada pelo filtro) ---
        ttk.Label(frame, text="Versão:", font=("Helvetica", 11)).grid(row=2, column=0, sticky="w", pady=6)
        version_combo = ttk.Combobox(frame, state="readonly")
        version_combo.grid(row=2, column=1, sticky="ew", pady=6, padx=(10, 6))
        
        download_btn = ttk.Button(
            frame, 
            text="Baixar", 
            bootstyle="info-outline", 
            width=8,
            command=lambda: self.open_version_downloader(dialog, version_combo) 
        )
        download_btn.grid(row=2, column=2, sticky="w", pady=6, padx=(0, 0))


        # --- Função de Atualização da Lista ---
        def update_version_list(event=None):
            # Pega o nome bonito do filtro (ex: "Vanilla")
            selected_filter_name = filter_combo.get()
            # Converte para a chave interna (ex: "vanilla")
            selected_category_key = filter_categories_map.get(selected_filter_name, "todos")
            
            # Pega a lista de tuplas (pretty_name, real_name)
            versions_to_show_tuples = all_versions_classified[selected_category_key]
            
            # Pega apenas os nomes bonitos para mostrar no combobox
            display_names = [pretty for (pretty, real) in versions_to_show_tuples]
            
            version_combo["values"] = display_names
            
            if display_names:
                version_combo.set(display_names[0])
            else:
                version_combo.set("")
        
        # Binda a função ao filtro
        filter_combo.bind("<<ComboboxSelected>>", update_version_list)
        

        # --- Define os valores iniciais (DEPOIS que a função de update foi criada) ---
        saved_real_version = current_config.get("version")
        if saved_real_version:
            # Encontra a categoria da versão salva
            saved_category = self._classify_version(saved_real_version)
            
            # Acha o nome bonito do filtro (ex: "Vanilla")
            saved_filter_name = next(
                (name for name, key in filter_categories_map.items() if key == saved_category), 
                "Todos"
            )
            filter_combo.set(saved_filter_name)
            
            # Atualiza a lista de versões
            update_version_list()
            
            # Acha o nome bonito da versão salva
            saved_display_name = next(
                (display for display, real in dialog.version_mapping.items() if real == saved_real_version), 
                None
            )
            if saved_display_name in version_combo["values"]:
                version_combo.set(saved_display_name)
        else:
            # Padrão: "Todos"
            filter_combo.set("Todos")
            update_version_list()

        
        # --- Java ---
        ttk.Label(frame, text="Java:", font=("Helvetica", 11)).grid(row=3, column=0, sticky="w", pady=6)
        java_values = list(self.java_options.keys())
        java_combo_dialog = ttk.Combobox(frame, values=java_values, state="readonly")
        
        saved_java = current_config.get("java", default_java)
        if saved_java in java_values:
            java_combo_dialog.set(saved_java)
        elif java_values:
            java_combo_dialog.set(java_values[0]) 
            
        java_combo_dialog.grid(row=3, column=1, columnspan=2, sticky="ew", pady=6, padx=(10, 0))

        # --- RAM ---
        ttk.Label(frame, text="Alocar RAM:", font=("Helvetica", 11)).grid(row=4, column=0, sticky="w", pady=6)
        ram_values = ["2G", "3G", "4G", "6G", "8G", "10G", "12G", "16G"]
        ram_combo_dialog = ttk.Combobox(frame, values=ram_values, state="readonly")
        
        saved_ram = current_config.get("ram", default_ram)
        if saved_ram in ram_values:
            ram_combo_dialog.set(saved_ram)
        else:
            ram_combo_dialog.set(default_ram)
            
        ram_combo_dialog.grid(row=4, column=1, columnspan=2, sticky="ew", pady=6, padx=(10, 0))

        # --- Botão Confirmar ---
        def confirmar():
            if edit:
                modpack_name = name_combo.get().strip()
            else:
                modpack_name = name_entry.get().strip()
            
            display_str = version_combo.get().strip()
            # Pega o nome real (ex: "1.8.9-forge...") usando o nome bonito
            version_str = dialog.version_mapping.get(display_str) 
            
            java_str = java_combo_dialog.get().strip()
            ram_str = ram_combo_dialog.get().strip()

            if not modpack_name or not version_str or not java_str or not ram_str:
                return messagebox.showerror("Erro","Preencha todos os campos!", parent=dialog)
            
            if not edit and os.path.exists(os.path.join(MODPACKS_DIR, modpack_name)):
                return messagebox.showerror("Erro","Já existe um modpack com esse nome!", parent=dialog)
            
            config_data = {
                "name": modpack_name,
                "version": version_str, # Salva o nome real e complexo
                "java": java_str,
                "ram": ram_str
            }
            
            self.save_modpack_config(modpack_name, config_data)
                
            self.load_selections()
            self.selection_combo.set(modpack_name) 
            self.on_modpack_selected()
            dialog.destroy()

        ttk.Button(frame, text="Confirmar", bootstyle="success", command=confirmar).grid(row=5, column=0, columnspan=3, pady=20)

    def on_modpack_selected(self, event=None):
        """Salva o modpack e ATUALIZA O ÍCONE."""
        modpack_name = self.selection_combo.get()
        if not modpack_name: 
            return
        
        # 1. Salva este modpack como o "último usado"
        self.save_settings(modpack_name)
        
        # 2. Tenta carregar o ícone do modpack
        try:
            icon_path = os.path.join(MODPACKS_DIR, modpack_name, "icon.png")
            if os.path.exists(icon_path):
                img = Image.open(icon_path).resize((48, 48), Image.Resampling.LANCZOS)
            else:
                # Se não achar o icon.png, usa o padrão que já carregamos
                img = Image.open(os.path.join(BASE_DIR, "default_pack.png")).resize((48, 48), Image.Resampling.LANCZOS)
        
        except Exception:
            # Se tudo falhar (incluindo o padrão), usa o ícone vazio
            img = Image.new('RGBA', (48, 48), (0,0,0,0))
        
        # 3. Atualiza a imagem na UI
        self.modpack_icon_photo = ImageTk.PhotoImage(img)
        self.modpack_icon_label.config(image=self.modpack_icon_photo)

    def on_checkbox_toggled(self):
        """Salva o estado do checkbox quando ele é clicado."""
        # Pega o modpack atual para salvar junto
        modpack_name = self.selection_combo.get()
        self.save_settings(modpack_name)

    def _get_default_minecraft_path(self):
        """Retorna o caminho padrão do .minecraft dependendo do SO."""
        system = platform.system().lower()
        if system == "windows":
            path = os.path.join(os.getenv('APPDATA'), '.minecraft')
        elif system == "darwin": # macOS
            path = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', 'minecraft')
        else: # Linux
            path = os.path.join(os.path.expanduser('~'), '.minecraft')
        
        # Garante que ele exista, como você pediu
        os.makedirs(path, exist_ok=True)
        return path

    def _update_paths(self):
        """
        (RE)DEFINE as variáveis GLOBAIS de caminho (GAME_DIR, etc.)
        baseado na configuração 'self.use_default_minecraft_dir'.
        """
        # Diz ao Python que estamos mudando as variáveis GLOBAIS
        global GAME_DIR, VERSIONS_DIR, LIBRARIES_DIR, ASSETS_DIR
        
        if self.use_default_minecraft_dir:
            print("[DEBUG] Usando diretório padrão do .minecraft")
            GAME_DIR = self._get_default_minecraft_path()
        else:
            print("[DEBUG] Usando diretório local 'game'")
            GAME_DIR = os.path.join(BASE_DIR, "game")

        # Redefine os outros caminhos com base no GAME_DIR que acabamos de setar
        VERSIONS_DIR = os.path.join(GAME_DIR, "versions")
        LIBRARIES_DIR = os.path.join(GAME_DIR, "libraries")
        ASSETS_DIR = os.path.join(GAME_DIR, "assets")
        
        # Garante que os diretórios existam
        os.makedirs(GAME_DIR, exist_ok=True)
        os.makedirs(VERSIONS_DIR, exist_ok=True)
        os.makedirs(LIBRARIES_DIR, exist_ok=True)
        os.makedirs(ASSETS_DIR, exist_ok=True)
        
        print(f"[DEBUG] GAME_DIR definido para: {GAME_DIR}")

        # --- LÓGICA DO 'launcher_profiles.json' MOVIDA PARA CÁ ---
        LAUNCHER_PROFILES_PATH = os.path.join(GAME_DIR, "launcher_profiles.json")
        
        if not os.path.exists(LAUNCHER_PROFILES_PATH):
            print(f"AVISO: 'launcher_profiles.json' não encontrado. Criando um novo em {GAME_DIR}")
            
            DEFAULT_PROFILES_DATA = {
              "profiles": {
                "default-profile": {
                  "name": "Raposo_launcher" 
                }
              },
              "settings": {
                "crashAssistance": True
              },
              "version": 4
            }
            
            try:
                with open(LAUNCHER_PROFILES_PATH, "w", encoding="utf-8") as f:
                    json.dump(DEFAULT_PROFILES_DATA, f, indent=2)
            except Exception as e:
                print(f"ERRO: Não foi possível criar 'launcher_profiles.json': {e}")

    def save_modpack_config(self, modpack_name, data):
        """Salva os dados de configuração (version, java, ram) para um modpack."""
        path = os.path.join(MODPACKS_DIR, modpack_name, "config.json")
        
        # Garante que a pasta exista
        os.makedirs(os.path.dirname(path), exist_ok=True)
            
        # Tenta carregar dados antigos para não sobrescrever
        full_data = self.load_modpack_config(modpack_name)
        full_data.update(data) # Atualiza com os novos dados
        
        try:
            with open(path, "w", encoding="utf-8") as f: 
                json.dump(full_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Erro ao salvar config do modpack {modpack_name}: {e}")

    def load_modpack_config(self, modpack_name):
        """Carrega os dados de configuração (version, java, ram) de um modpack."""
        path = os.path.join(MODPACKS_DIR, modpack_name, "config.json")
        
        if not os.path.exists(path):
            return {} # Retorna vazio se não houver config
            
        try:
            with open(path, "r", encoding="utf-8") as f: 
                return json.load(f)
        except Exception as e:
            print(f"Erro ao carregar config do modpack {modpack_name}: {e}")
            return {}
            
    def load_last_modpack_selection(self):
        """
        Carrega a seleção do último modpack.
        Esta função deve ser chamada DEPOIS que a UI e os modpacks
        foram carregados (load_selections).
        """
        data = {}
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass # Erro já foi reportado por load_settings

        modpack_values = self.selection_combo.cget("values")
        last_modpack = data.get("last_modpack", "")
        
        if last_modpack in modpack_values:
            self.selection_combo.set(last_modpack)
        
        # Chama on_modpack_selected para carregar o ícone
        self.on_modpack_selected()

    # ---------------------------
    # Settings (RAM)
    # ---------------------------
    def load_settings(self):
        """
        Carrega as configurações GLOBAIS do settings.json.
        Se o arquivo não existir ou uma chave estiver faltando, 
        ele define os padrões e salva o arquivo.
        """
        data = {}
        file_needs_update = False

        if not os.path.exists(SETTINGS_FILE):
            print(f"[DEBUG] {SETTINGS_FILE} não encontrado. Criando com padrões.")
            file_needs_update = True
        else:
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if not data: # Se o arquivo estiver vazio
                         file_needs_update = True
            except Exception as e:
                print(f"Erro ao carregar settings.json: {e}. Usando padrões.")
                file_needs_update = True
        
        # --- MUDANÇA: Checa se a chave existe ---
        # Se os dados foram carregados (não vazios) mas a chave falta...
        if "use_default_minecraft_dir" not in data:
            print("[DEBUG] Migrando settings: Adicionando 'use_default_minecraft_dir'.")
            file_needs_update = True
        # --- FIM DA MUDANÇA ---
            
        # 1. Carrega os valores do 'data' (ou seus padrões) para a classe
        self.close_after_launch.set(data.get("close_after_launch", False))
        self.show_terminal.set(data.get("show_terminal", True))
        self.use_default_minecraft_dir = data.get("use_default_minecraft_dir", False)
        
        # 2. Se o arquivo era novo ou precisava da chave, salva
        if file_needs_update:
            # Pega o last_modpack dos dados (pode ser None)
            last_modpack_name = data.get("last_modpack")
            # Salva o arquivo. save_settings() vai ler os valores de self
            self.save_settings(last_modpack_name)

    def save_settings(self, modpack_name):
        """Salva as configurações GLOBAIS."""
            
        data = {
            "last_modpack": modpack_name,
            "close_after_launch": self.close_after_launch.get(),
            "show_terminal": self.show_terminal.get(),
            "use_default_minecraft_dir": self.use_default_minecraft_dir
        }
        
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível salvar as configurações: {e}")

    # ------------------------------------
    # --- MÉTODO NOVO (ADICIONE ISTO) ---
    # ------------------------------------
    def abrir_pasta_modpack(self):
        """Abre a pasta do modpack selecionado no gerenciador de arquivos do SO."""
        
        # 1. Pega o nome do modpack selecionado
        modpack_name = self.selection_combo.get().strip()
        if not modpack_name:
            return messagebox.showerror("Erro", "Nenhum modpack selecionado!")
            
        # 2. Monta o caminho da pasta
        # Não precisamos mais checar 'tipo', pois SÓ há modpacks.
        modpack_path = os.path.join(MODPACKS_DIR, modpack_name)
        
        # Garante que a pasta exista
        os.makedirs(modpack_path, exist_ok=True) 
        
        # 3. Abre a pasta usando o comando nativo do Sistema Operacional
        try:
            system = platform.system().lower()
            if system == "windows":
                os.startfile(modpack_path) # Comando do Windows
            elif system == "darwin": # macOS
                subprocess.Popen(["open", modpack_path])
            else: # Linux
                subprocess.Popen(["xdg-open", modpack_path])
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível abrir a pasta: {e}")

    def exportar_modpack(self):
        """Exporta o modpack selecionado como um arquivo .fox (zip)."""
        
        # 1. Pega o modpack selecionado
        modpack_name = self.selection_combo.get().strip()
        if not modpack_name:
            return messagebox.showerror("Erro", "Nenhum modpack selecionado para exportar!")
            
        source_dir = os.path.join(MODPACKS_DIR, modpack_name)
        if not os.path.isdir(source_dir):
             return messagebox.showerror("Erro", f"A pasta do modpack '{modpack_name}' não foi encontrada.")

        # 2. Pede ao usuário onde salvar o .fox (SUA IDEIA)
        file_path = filedialog.asksaveasfilename(
            title=f"Exportar {modpack_name}",
            defaultextension=".fox",
            filetypes=[("Arquivo Raposo Modpack", "*.fox")],
            initialfile=f"{modpack_name}.fox"
        )
        
        if not file_path:
            return # Usuário cancelou

        # 3. Inicia o thread para fazer o trabalho pesado
        try:
            self.status_label.config(text=f"Exportando {modpack_name}...", bootstyle=INFO)
            threading.Thread(
                target=self._export_modpack_thread, 
                args=(modpack_name, file_path), 
                daemon=True
            ).start()
            
        except Exception as e:
            messagebox.showerror("Erro de Exportação", f"Falha ao iniciar a exportação: {e}")
            self.status_label.config(text="")

    def importar_modpack(self):
        """Importa um modpack de um arquivo .fox para a pasta modpacks/."""
        
        # 1. Pede ao usuário qual .fox ele quer importar
        file_path = filedialog.askopenfilename(
            title="Importar Modpack",
            filetypes=[("Arquivo Raposo Modpack", "*.fox")] # <--- SUA IDEIA
        )
        
        if not file_path:
            return # Usuário cancelou
            
        # 2. Inicia o thread para fazer o trabalho pesado
        try:
            self.status_label.config(text="Importando modpack...", bootstyle=INFO)
            threading.Thread(
                target=self._import_modpack_thread, 
                args=(file_path,), 
                daemon=True
            ).start()

        except Exception as e:
            messagebox.showerror("Erro de Importação", f"Falha ao iniciar a importação: {e}")
            self.status_label.config(text="")

    def _import_modpack_thread(self, file_path):
        """(THREAD) Verifica o .fox e descompacta em segundo plano."""
        try:
            modpack_name = None
            
            # --- LÓGICA DE "ESPIAR" ---
            try:
                with zipfile.ZipFile(file_path, 'r') as zf:
                    namelist = zf.namelist()
                    if not namelist:
                        raise Exception("Arquivo .fox está vazio ou corrompido.")
                        
                    # Pega o nome da pasta raiz dentro do .zip (ex: "Familia-Rp/")
                    # split('/') trata subpastas (ex: "Familia-Rp/mods/meu-mod.jar")
                    root_folder = namelist[0].split('/')[0]
                    
                    # Se a pasta raiz estiver vazia ou for estranha
                    if not root_folder or root_folder.startswith('.'):
                         raise Exception("Arquivo .fox mal formatado. Nenhuma pasta raiz encontrada.")
                    
                    modpack_name = root_folder
            
            except zipfile.BadZipFile:
                 raise Exception("Erro: Não é um arquivo .fox válido (não é um .zip).")
            except Exception as e:
                raise Exception(f"Erro ao ler o .fox: {e}")
            # --- FIM DA LÓGICA DE "ESPIAR" ---

            # 2. Agora que temos o nome, CHECAMOS A COLISÃO
            target_path = os.path.join(MODPACKS_DIR, modpack_name)
            if os.path.exists(target_path):
                raise Exception(f"O modpack '{modpack_name}' já existe! Apague o antigo primeiro.")

            # 3. Se tudo deu certo, descompacta
            # (Nós ainda usamos 'zip' como formato, pois .fox É um zip)
            shutil.unpack_archive(
                filename=file_path,
                extract_dir=MODPACKS_DIR,
                format="zip"
            )
            
            # 4. Envia a mensagem de sucesso
            self.ui_queue.put({
                "type": "import_success",
                "title": "Sucesso",
                "text": f"Modpack '{modpack_name}' importado com sucesso!"
            })

        except Exception as e:
            # Envia qualquer erro que tenha acontecido (incluindo a colisão)
            self.ui_queue.put({
                "type": "popup_error",
                "text": str(e) # Mostra a mensagem de erro direto (ex: "O modpack já existe!")
            })
            
        finally:
            # Limpa o status
            self.ui_queue.put({"type": "status", "text": ""})

    def _export_modpack_thread(self, modpack_name, file_path):
        """(THREAD) Cria o arquivo .zip e o renomeia para .fox."""
        
        # 1. Define o caminho-base para o 'shutil' (ex: C:/.../Familia-Rp)
        # Ele vai criar "C:/.../Familia-Rp.zip"
        save_path_without_extension = file_path.rsplit('.', 1)[0]
        
        created_zip_path = None # Para o 'finally'
        
        try:
            # 2. Cria o arquivo .zip
            created_zip_path = shutil.make_archive(
                base_name=save_path_without_extension, 
                format="zip",
                root_dir=MODPACKS_DIR,
                base_dir=modpack_name
            )
            
            # <--- CORREÇÃO AQUI (RENOMEAR) ---
            # 3. Renomeia o .zip para .fox (a mágica)
            # (Se o .fox já existir, apaga antes de renomear)
            if os.path.exists(file_path):
                os.remove(file_path)
            os.rename(created_zip_path, file_path) # Renomeia "Familia-Rp.zip" para "Familia-Rp.fox"
            # <--- FIM DA CORREÇÃO ---
            
            # 4. Envia a mensagem de sucesso
            self.ui_queue.put({
                "type": "popup_success",
                "title": "Sucesso",
                "text": f"Modpack '{modpack_name}' exportado com sucesso para:\n{file_path}"
            })
            
        except Exception as e:
            # 5. Envia a mensagem de erro
            self.ui_queue.put({
                "type": "popup_error",
                "text": f"Falha ao criar o arquivo .fox: {e}"
            })
            # Tenta apagar o .zip que falhou, se ele existir
            if created_zip_path and os.path.exists(created_zip_path):
                os.remove(created_zip_path)
                
        finally:
            # Limpa o status
            self.ui_queue.put({"type": "status", "text": ""})

    # ---------------------------
    # Natives (CORRIGIDO)
    # ---------------------------
    def extract_natives(self, version_data, version):
        """
        Extrai os arquivos nativos. (V16: Esta função AGORA ASSUME
        que todos os JARs nativos já foram baixados).
        """
        natives_dir = os.path.join(GAME_DIR, "natives", version)
        os.makedirs(natives_dir, exist_ok=True)
        
        os_name = platform.system().lower()
        current_os = "windows" if "windows" in os_name else "linux" if "linux" in os_name else "osx"

        native_features = {} # Nativos só usam regras 'os'

        for lib in version_data.get("libraries", []):
            if not self.check_rules(lib, native_features):
                continue

            natives = lib.get("natives")
            classifiers = lib.get("downloads", {}).get("classifiers", {})
            if not natives and not classifiers:
                continue 

            native_classifier_key = None
            if natives:
                native_classifier_key = natives.get(current_os)
            if not native_classifier_key:
                native_classifier_key = f"natives-{current_os}"
            
            native_info = classifiers.get(native_classifier_key)
            if native_info:
                jar_path = os.path.join(LIBRARIES_DIR, native_info["path"])
                
                # --- LÓGICA DE DOWNLOAD REMOVIDA ---
                
                if os.path.exists(jar_path): # Se o download (feito antes) funcionou
                    try:
                        extract_rules = lib.get("extract", {})
                        excludes = extract_rules.get("exclude", [])

                        with zipfile.ZipFile(jar_path, "r") as zf:
                            for member in zf.namelist():
                                if not any(member.startswith(ex) for ex in excludes):
                                    zf.extract(member, natives_dir)
                    except Exception as e:
                        print(f"Erro ao extrair native {jar_path}: {e}")
                        continue
                else:
                    # Se o arquivo ainda não existe, é um erro de lógica, mas não baixamos aqui.
                    print(f"Aviso: JAR Nativo não encontrado durante a extração: {jar_path}")
                    
        return natives_dir

    # ---------------------------
    # Métodos de Ajuda para Inicialização (NOVOS / CORRIGIDOS)
    # ---------------------------
    
    # CORRIGIDO: Esta função lê as regras de uma biblioteca
    # e decide se ela deve ser usada neste SO.
    def check_rules(self, entry, features) -> bool:
        """
        Verifica as regras de uma biblioteca ou argumento.
        Agora entende 'os' E 'features'.
        """
        if "rules" not in entry:
            return True # Sem regras, incluir sempre

        os_name = platform.system().lower()
        current_os = "windows" if "windows" in os_name else "linux" if "linux" in os_name else "osx"
        
        rules = entry["rules"]
        
        # O padrão (se houver regras) é NÃO permitir,
        # a menos que uma regra explicitamente permita.
        action_to_take = "disallow" 
        
        for rule in rules:
            action = rule["action"]
            applies = True # Supõe que a regra se aplica, a menos que uma condição falhe
            
            # 1. Checar SO
            if "os" in rule:
                if rule["os"].get("name") != current_os:
                    applies = False # Regra de SO não bateu, não se aplica
            
            # 2. Checar Features (A GRANDE MUDANÇA)
            if "features" in rule and applies:
                for feature, required_value in rule["features"].items():
                    # Pega o valor da feature no nosso dicionário (padrão False)
                    our_value = features.get(feature, False) 
                    
                    if our_value != required_value:
                        applies = False # Regra de feature não bateu
                        break # Para de checar outras features nesta regra
            
            # 3. Determinar ação
            if applies:
                # Esta regra é a vencedora (por enquanto)
                action_to_take = action
                
        return action_to_take == "allow"

    # NOVO: Esta função substitui marcadores como ${...} por valores reais.
    def replace_arg(self, arg_str, replacements):
        """Substitui os marcadores de argumentos (ex: ${auth_player_name})"""
        for key, value in replacements.items():
            arg_str = arg_str.replace(key, value)
        return arg_str

    def download_file(self, url, path, filename):
        """Baixa um arquivo de um URL para um caminho específico (Thread-safe)."""
        
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        try:
            print(f"[DOWNLOAD] (Trabalhador) Baixando: {filename}")
            
            # <--- CORREÇÃO AQUI (O "DISFARCE") ---
            # Define um "User-Agent" para parecer um navegador
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'
            }
            
            # <--- MUDANÇA AQUI: Usar 'with' para garantir que a ligação fecha ---
            with requests.get(url, stream=True, headers=headers) as response:
                response.raise_for_status()
                
                with open(path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
            # --- FIM DA MUDANÇA ---
            
            return filename 
            
        except Exception as e:
            print(f"[DOWNLOAD] FALHA ao baixar {filename}: {e}")
            raise e

    def download_assets(self, asset_index_path):
        """Lê o asset_index.json e baixa todos os assets (Thread-safe)."""
        
        try:
            with open(asset_index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            raise Exception(f"Erro ao ler asset_index: {e}") # Envia o erro para o thread

        assets_to_download = data.get("objects", {})
        total_assets = len(assets_to_download)
        download_count = 0
        
        base_url = "https://resources.download.minecraft.net/"
        
        # --- NOVO: Agrupa os downloads ---
        # Conta quantos arquivos realmente *precisam* ser baixados
        # (Isso impede que a barra de progresso pule)
        assets_to_check = []
        for asset_name, info in assets_to_download.items():
            asset_hash = info.get("hash")
            if not asset_hash: continue
            
            hash_prefix = asset_hash[:2]
            asset_path = os.path.join(ASSETS_DIR, "objects", hash_prefix, asset_hash)
            
            if not os.path.exists(asset_path):
                asset_url = f"{base_url}{hash_prefix}/{asset_hash}"
                filename = asset_name.split('/')[-1]
                assets_to_check.append((asset_url, asset_path, filename))
        
        total_to_download = len(assets_to_check)
        if total_to_download == 0:
            print("[ASSET] Todos os assets já estão atualizados.")
            return

        print(f"[ASSET] Faltando {total_to_download} assets. Iniciando download...")
        
        # Inicia a barra de progresso DETERMINADA
        self.ui_queue.put({"type": "progress_start_determinate", "max": total_to_download})

        for i, (asset_url, asset_path, filename) in enumerate(assets_to_check):
            # Atualiza a UI
            self.ui_queue.put({"type": "status", "text": f"Baixando asset ({i+1}/{total_to_download})"})
            
            # Baixa o arquivo
            self.download_file(asset_url, asset_path, filename)
            
            # Avança a barra
            self.ui_queue.put({"type": "progress_step"})

        print(f"[ASSET] Download de {total_to_download} assets concluído.")

    def process_ui_queue(self):
        """Processa mensagens da fila de background para a UI (thread-safe)."""
        try:
            message = self.ui_queue.get_nowait()
            
            msg_type = message.get("type")

            if msg_type == "status":
                self.status_label.config(text=message.get("text", ""), bootstyle=message.get("style", INFO))
            
            elif msg_type == "progress_start_indeterminate":
                self.progressbar.stop() 
                self.progressbar.config(mode="indeterminate", value=0)
                self.progressbar.start()
                
            elif msg_type == "progress_start_determinate":
                self.progressbar.stop()
                self.progressbar.config(mode="determinate", maximum=message.get("max", 100), value=0)
            
            elif msg_type == "progress_set_value":
                self.progressbar.config(value=message.get("value", 0))
                
            elif msg_type == "progress_stop":
                self.progressbar.stop()
                self.progressbar.config(value=0)
                
            elif msg_type == "button_toggle":
                self.start_button.config(state=message.get("state", "disabled"))
                
            elif msg_type == "popup_error":
                messagebox.showerror("Erro Fatal", message.get("text", "Erro desconhecido"))

            # (As funções de popup de import/export que adicionamos)
            elif msg_type == "popup_success":
                messagebox.showinfo(message.get("title", "Sucesso"), message.get("text", "Operação concluída."))
            
            elif msg_type == "import_success":
                self.load_selections()
                messagebox.showinfo(message.get("title", "Sucesso"), message.get("text", "Operação concluída."))
            
            # --- ESTE BLOCO FOI REMOVIDO ---
            # elif msg_type == "launch_game":
            #     ... (Toda a lógica de Popen e _wait_for_game_close_thread foi movida) ...
            
            # --- ESTE BLOCO FOI ADICIONADO ---
            elif msg_type == "hide_launcher":
                print("[DEBUG] (UI Thread) Escondendo a janela.")
                self.withdraw()
            
            # <--- CORREÇÃO AQUI (E MUDANÇA DO DISCORD) ---
            elif msg_type == "show_launcher":
                print("[DEBUG] Reabrindo o launcher...")
                self.deiconify() # Mostra a janela
                self.lift() # Traz para a frente
                self.focus_force() # Força o foco

                # --- MUDANÇA AQUI: Reseta o status do Discord ---
                print("[Discord RPC] Atualizando status para: No menu")
                self.discord_state = "No menu principal"
                self.discord_details = "Escolhendo um modpack..."
                self.discord_small_image = None # Volta a ser None (invisível)
                self.discord_small_text = "Raposo Launcher"
                # --- FIM DA MUDANÇA ---
                
                # Limpa a mensagem "iniciado!"
                self.status_label.config(text="") 
            # <--- FIM DA CORREÇÃO ---

        except Exception:
            pass # Fila vazia
            
        self.after(100, self.process_ui_queue)

    def on_start_button_click(self):
        """O que acontece quando o botão 'START' é clicado (UI Thread)."""
        
        # Desabilita o botão
        self.start_button.config(state="disabled")
        self.status_label.config(text="Preparando...", bootstyle=INFO) # Era 'self_label'
        self.progressbar.config(mode="indeterminate", value=0)
        self.progressbar.start()
        
        # Inicia o processo de download/inicialização em um thread separado
        threading.Thread(target=self.iniciar_minecraft_thread, daemon=True).start()

    def iniciar_minecraft_thread(self):
        try:
            # --- 0. PEGAR CONFIGURAÇÕES ---
            account_id = self.active_account
            modpack_name = self.selection_combo.get()
            
            account = next((a for a in self.accounts if a["id"] == account_id), None)
            if not account: raise Exception("Nenhuma conta selecionada")
            username = account["name"]
            
            if not modpack_name: raise Exception("Nenhum modpack selecionado!")
            
            modpack = modpack_name 
            config = self.load_modpack_config(modpack)
            version = config.get("version")
            java_name = config.get("java", "java") 
            ram_alloc = config.get("ram", "4G")
            
            if not version: raise Exception(f"O modpack '{modpack}' não tem uma versão definida!")
            
            print("[Discord RPC] Atualizando status para: Jogando")
            self.discord_state = f"Jogando {modpack_name}"
            self.discord_details = f"Versão: {version}"

            # --- MUDANÇA AQUI: Adicionamos o NeoForge ---
            if "fabric" in version.lower():
                self.discord_small_image = "fabric_icon" # O nome que você deu no portal
                self.discord_small_text = "Jogando com Fabric"
            elif "neoforge" in version.lower():
                self.discord_small_image = "neoforge_icon" # O nome que você deve subir no portal
                self.discord_small_text = "Jogando com NeoForge"
            elif "forge" in version.lower():
                self.discord_small_image = "forge_icon"
                self.discord_small_text = "Jogando com Forge"
            elif "optifine" in version.lower():
                self.discord_small_image = "optifine_icon"
                self.discord_small_text = "Jogando com OptiFine"
            else:
                self.discord_small_image = "default_icon" # Use o "default_icon" que você subiu
                self.discord_small_text = "Jogando Minecraft"
            # --- FIM DA MUDANÇA ---

            game_dir = os.path.join(MODPACKS_DIR, modpack)
            os.makedirs(game_dir, exist_ok=True)
            java_exec = self.get_selected_java(java_name)
            
            self.ui_queue.put({"type": "status", "text": "Verificando arquivos..."})
            self.ui_queue.put({"type": "progress_start_indeterminate"})

            # --- 1. PREPARAR LISTA DE TAREFAS DE DOWNLOAD ---
            tasks_to_download = [] 
            version_data = {}      
            lib_features = {}      
            
            version_dir = os.path.join(VERSIONS_DIR, version)
            version_json = os.path.join(version_dir, f"{version}.json")
            
            if not os.path.exists(version_json):
                is_vanilla = "forge" not in version.lower() and \
                             "fabric" not in version.lower() and \
                             "optifine" not in version.lower()
                
                if is_vanilla:
                    try:
                        print(f"[DEBUG] Tentando baixar .json vanilla para {version}")
                        self._ensure_vanilla_json_exists(version) 
                    except Exception as e:
                        raise FileNotFoundError(f"Falha ao baixar o JSON '{version}' da Mojang: {e}")
                else:
                    raise FileNotFoundError(f"JSON '{version}' não encontrado! A versão foi instalada corretamente na pasta 'game/versions'?")
            
            with open(version_json, "r", encoding="utf-8") as f: child_data = json.load(f)
                 
            parent_version = child_data.get("inheritsFrom")
            parent_json_path = None
            parent_data = {}
            
            if parent_version:
                parent_json_path = os.path.join(VERSIONS_DIR, parent_version, f"{parent_version}.json")
                if not os.path.exists(parent_json_path):
                    try:
                        self._ensure_vanilla_json_exists(parent_version)
                    except Exception as e:
                         raise FileNotFoundError(f"Falha ao baixar o JSON pai '{parent_version}': {e}")

            # --- 3. CONTAR TODO O RESTO ---
            self.ui_queue.put({"type": "status", "text": "Contando arquivos..."})
            self.ui_queue.put({"type": "progress_start_indeterminate"})
            
            tasks_to_download = [] 

            with open(version_json, "r", encoding="utf-8") as f: child_data = json.load(f)
            if parent_json_path and os.path.exists(parent_json_path):
                with open(parent_json_path, "r", encoding="utf-8") as f: parent_data = json.load(f)

            version_data = parent_data.copy()
            version_data.update(child_data) 
            parent_libs = parent_data.get("libraries", []) 
            child_libs = child_data.get("libraries", [])
            version_data["libraries"] = parent_libs + child_libs
            version_data["mainClass"] = child_data.get("mainClass", parent_data.get("mainClass"))
            
            main_class_detectada = version_data.get("mainClass", "")
            is_modern_forge = main_class_detectada == "cpw.mods.bootstraplauncher.BootstrapLauncher"
            is_modern_fabric = main_class_detectada == "net.fabricmc.loader.impl.launch.knot.KnotClient"

            main_jar = os.path.join(version_dir, f"{version}.jar")
            if not os.path.exists(main_jar):
                url = child_data.get("downloads", {}).get("client", {}).get("url")
                if url: tasks_to_download.append((url, main_jar, f"{version}.jar"))

            parent_jar = None
            if parent_version and not is_modern_forge:
                parent_jar = os.path.join(VERSIONS_DIR, parent_version, f"{parent_version}.jar")
                if not os.path.exists(parent_jar):
                    url = parent_data.get("downloads", {}).get("client", {}).get("url")
                    if url: tasks_to_download.append((url, parent_jar, f"{parent_version}.jar"))

            # --- 3c. Contar Bibliotecas ---
            for lib in version_data.get("libraries", []):
                if not self.check_rules(lib, lib_features): continue
                
                lib_name = lib.get("name", "NOME_DESCONHECIDO")
                downloads = lib.get("downloads", {})
                artifact = downloads.get("artifact")
                classifiers = downloads.get("classifiers")
                natives = lib.get("natives")
                
                lib_path, url, filename, lib_path_str = None, None, None, None
                
                if artifact and artifact.get("path"):
                    lib_path_str = artifact.get("path")
                elif not artifact and not classifiers and not natives:
                    try: 
                        parts = lib_name.split(':')
                        group = parts[0].replace('.', '/')
                        name = parts[1]
                        ver = parts[2]
                        classifier = f"-{parts[3]}" if len(parts) > 3 else ""
                        filename = f"{name}-{ver}{classifier}.jar"
                        lib_path_str = f"{group}/{name}/{ver}/{filename}"
                    except Exception as e:
                        print(f"[DEBUG] Falha ao construir caminho para {lib_name}: {e}")
                        continue
                else:
                    pass

                if lib_path_str:
                    lib_path = os.path.join(LIBRARIES_DIR, lib_path_str)
                    filename = lib_path_str.split('/')[-1]

                    custom_repo_url = lib.get("url") 
                    
                    if custom_repo_url:
                        url = custom_repo_url.rstrip('/') + '/' + lib_path_str
                    elif artifact and artifact.get("url"):
                        url = artifact.get("url")
                    else:
                        if "net.minecraftforge" in lib_path_str:
                            url = f"https://maven.minecraftforge.net/{lib_path_str}"
                        else:
                            url = f"https://libraries.minecraft.net/{lib_path_str}"

                    if lib_path and not os.path.exists(lib_path):
                        if not url:
                            print(f"[AVISO] URL não encontrado para {lib_name}, pulando download.")
                            continue
                        tasks_to_download.append((url, lib_path, filename))
                
                if classifiers or natives:
                    os_name = platform.system().lower()
                    current_os = "windows" if "windows" in os_name else "linux" if "linux" in os_name else "osx"
                    native_classifier_key = None
                    if natives: native_classifier_key = natives.get(current_os)
                    if not native_classifier_key: native_classifier_key = f"natives-{current_os}"
                    
                    native_info = classifiers.get(native_classifier_key)
                    if native_info:
                        native_path = os.path.join(LIBRARIES_DIR, native_info["path"])
                        if not os.path.exists(native_path):
                            tasks_to_download.append((native_info["url"], native_path, native_info["path"].split('/')[-1]))

            # 3d. Contar Assets
            asset_index = version_data.get("assetIndex", {}).get("id", "legacy")
            asset_index_url = version_data.get("assetIndex", {}).get("url")
            asset_index_path = os.path.join(ASSETS_DIR, "indexes", f"{asset_index}.json")
            
            if asset_index_url and not os.path.exists(asset_index_path):
                self.download_file(asset_index_url, asset_index_path, f"{asset_index}.json")

            if os.path.exists(asset_index_path):
                with open(asset_index_path, "r", encoding="utf-8") as f: data = json.load(f)
                base_url = "https://resources.download.minecraft.net/"
                for asset_name, info in data.get("objects", {}).items():
                    asset_hash = info.get("hash")
                    if not asset_hash: continue
                    hash_prefix = asset_hash[:2]
                    asset_path = os.path.join(ASSETS_DIR, "objects", hash_prefix, asset_hash)
                    if not os.path.exists(asset_path):
                        asset_url = f"{base_url}{hash_prefix}/{asset_hash}"
                        tasks_to_download.append((asset_url, asset_path, asset_hash[:10]))
            
            # --- 4. EXECUTAR DOWNLOADS PARALELOS ---
            total_downloads = len(tasks_to_download)
            if total_downloads > 0:
                print(f"[DOWNLOAD] Total de {total_downloads} arquivos faltando. Iniciando {min(total_downloads, 10)} downloads paralelos...")
                self.ui_queue.put({"type": "progress_start_determinate", "max": total_downloads})
                
                completed_count = 0
                last_reported_percent = -1
                
                with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                    futures = {executor.submit(self.download_file, url, path, filename): (url, filename) for (url, path, filename) in tasks_to_download}
                    
                    for future in concurrent.futures.as_completed(futures):
                        url, filename = futures[future]
                        try:
                            result = future.result() 
                        except Exception as e:
                            print(f"FALHA no download (trabalhador): {filename} - {e}")
                        
                        completed_count += 1
                        current_percent = int((completed_count / total_downloads) * 100)
                        
                        if current_percent > last_reported_percent:
                            self.ui_queue.put({"type": "progress_set_value", "value": completed_count})
                            self.ui_queue.put({"type": "status", "text": f"Baixando ({current_percent}%)"})
                            last_reported_percent = current_percent
                
                print(f"[DOWNLOAD] Downloads paralelos concluídos.")
            else:
                print("[DEBUG] Todos os arquivos já estão baixados e atualizados.")
            
            # --- 5. CONSTRUIR CLASSPATH ---
            self.ui_queue.put({"type": "status", "text": "Construindo classpath..."})
            self.ui_queue.put({"type": "progress_start_indeterminate"}) 
            
            # --- MUDANÇA AQUI: Trocado '[]' por 'set()' ---
            classpath_set = set()
            processed_libs = set() 

            # --- MUDANÇA AQUI: Trocado '.append()' por '.add()' ---
            if os.path.exists(main_jar): classpath_set.add(main_jar)
            if parent_jar and os.path.exists(parent_jar): classpath_set.add(parent_jar)

            for lib in version_data.get("libraries", []):
                lib_name = lib.get("name", "NOME_DESCONHECIDO")
                if lib_name in processed_libs: continue
                processed_libs.add(lib_name)
                if not self.check_rules(lib, lib_features): continue 
                
                downloads = lib.get("downloads", {})
                artifact = downloads.get("artifact")
                classifiers = downloads.get("classifiers")
                natives = lib.get("natives")
                
                lib_path = None
                
                if artifact and artifact.get("path"):
                    lib_path = os.path.join(LIBRARIES_DIR, artifact["path"])
                    
                elif downloads.get("path") and not classifiers and not natives:
                    lib_path = os.path.join(LIBRARIES_DIR, downloads["path"])

                elif not artifact and not classifiers and not natives:
                    try:
                        parts = lib_name.split(':')
                        group = parts[0].replace('.', '/')
                        name = parts[1]
                        ver = parts[2]
                        classifier = f"-{parts[3]}" if len(parts) > 3 else ""
                        
                        filename = f"{name}-{ver}{classifier}.jar"
                        lib_path_str = f"{group}/{name}/{ver}/{filename}"
                        lib_path = os.path.join(LIBRARIES_DIR, lib_path_str)
                    except Exception:
                        continue 
                
                if lib_path and os.path.exists(lib_path):
                    # --- MUDANÇA AQUI: Trocado '.append()' por '.add()' ---
                    classpath_set.add(lib_path)
            
            # --- MUDANÇA AQUI: Trocado 'classpath_list' por 'classpath_set' ---
            classpath_str = (";" if os.name == "nt" else ":").join(classpath_set)

            # --- 6. Extrair Natives ---
            self.ui_queue.put({"type": "status", "text": "Extraindo nativos..."})
            natives_dir = self.extract_natives(version_data, version)

            # --- 7. Preparar Argumentos ---
            self.ui_queue.put({"type": "status", "text": "Preparando argumentos..."})
            
            main_class = version_data.get("mainClass")
            if not main_class: raise Exception("mainClass não encontrado no JSON")
            
            use_uuid = account.get("uuid") or offline_uuid_for(username)
            access_token = "0"
            
            jvm_args = []
            game_args = []
            
            # --- 8. LÓGICA DE DUAS VIAS (MODERNA vs LEGADA) ---
            
            if "minecraftArguments" in version_data:
                print("[DEBUG] Detecção: Versão LEGADA (usa 'minecraftArguments')")
                
                replacements = {
                    "${auth_player_name}": username,
                    "${auth_uuid}": use_uuid,
                    "${auth_access_token}": access_token,
                    "${auth_session}": access_token, 
                    "${user_type}": "legacy",
                    "${user_properties}": "{}",
                    "${version_name}": version,
                    "${game_directory}": game_dir,
                    "${assets_root}": ASSETS_DIR,
                    "${game_assets}": ASSETS_DIR, 
                    "${assets_index_name}": asset_index,
                    "${version_type}": version_data.get("type", "release"),
                }
                
                jvm_args.append(f"-Xmx{ram_alloc}")
                jvm_args.append(f"-Xms{ram_alloc}")
                print(f"[DEBUG] Alocando RAM (do modpack): -Xmx{ram_alloc}")
                if platform.system().lower() == "darwin":
                    jvm_args.append("-XstartOnFirstThread")
                
                jvm_args.append(f"-Djava.library.path={natives_dir}") 
                jvm_args.append("-cp") 
                jvm_args.append(classpath_str) 

                mc_args_str = version_data["minecraftArguments"]
                game_args = self.replace_arg(mc_args_str, replacements).split()

            elif "arguments" in version_data:
                print("[DEBUG] Detecção: Versão MODERNA (usa 'arguments')")

                replacements = {
                    "${auth_player_name}": username,
                    "${auth_uuid}": use_uuid,
                    "${auth_access_token}": access_token,
                    "${user_type}": "legacy",
                    "${user_properties}": "{}",
                    "${version_name}": version,
                    "${game_directory}": game_dir,
                    "${assets_root}": ASSETS_DIR,
                    "${assets_index_name}": asset_index, 
                    "${version_type}": version_data.get("type", "release"),
                    "${natives_directory}": natives_dir,
                    "${library_directory}": LIBRARIES_DIR,
                    "${classpath_separator}": (";" if os.name == "nt" else ":"),
                    "${classpath}": classpath_str, 
                    "${launcher_name}": "RaposoLauncher",
                    "${launcher_version}": "1.0"
                }
            
                features = {
                    "is_demo_user": False,
                    "has_custom_resolution": False,
                    "has_quick_plays_support": False,
                    "is_quick_play_singleplayer": False,
                    "is_quick_play_multiplayer": False,
                    "is_quick_play_realms": False
                }
                
                is_modern_vanilla = (
                    not is_modern_forge 
                    and not is_modern_fabric 
                    and not parent_version
                    and ("1.19" in version or "1.20" in version or "1.21" in version)
                )

                jvm_args.append(f"-Xmx{ram_alloc}")
                jvm_args.append(f"-Xms{ram_alloc}")
                print(f"[DEBUG] Alocando RAM (do modpack): -Xmx{ram_alloc}")
                
                if platform.system().lower() == "darwin":
                    jvm_args.append("-XstartOnFirstThread")
                
                if is_modern_vanilla:
                    print("[DEBUG] Adicionando flag de modo offline do Authlib.")
                    jvm_args.append("-Dauthlib.environment=offline")

                if "jvm" in version_data["arguments"]:
                    for arg_entry in version_data["arguments"]["jvm"]:
                        if self.check_rules(arg_entry, features):
                            values_to_add = []
                            if isinstance(arg_entry, dict):
                                value = arg_entry.get("value")
                                if isinstance(value, list): values_to_add = value
                                elif isinstance(value, str): values_to_add = [value]
                            elif isinstance(arg_entry, str):
                                values_to_add = [arg_entry]
                            
                            for v in values_to_add:
                                 if "net.minecraft.client.main.Main" in v:
                                     print(f"[DEBUG] Ignorando argumento JVM problemático: {v}")
                                     continue 
                                 
                                 jvm_args.append(self.replace_arg(v, replacements))
                
                if is_modern_forge or is_modern_fabric:
                    if is_modern_forge:
                        print("[DEBUG] Adicionando '-cp' (classpath) manual para o Forge Moderno.")
                    else:
                        print("[DEBUG] Adicionando '-cp' (classpath) manual para o Fabric.")
                    
                    jvm_args.append("-cp")
                    jvm_args.append(classpath_str)
                
                if "game" in version_data["arguments"]:
                    for arg_entry in version_data["arguments"]["game"]:
                        if self.check_rules(arg_entry, features):
                            values_to_add = []
                            if isinstance(arg_entry, dict):
                                value = arg_entry.get("value")
                                if isinstance(value, list): values_to_add = value
                                elif isinstance(value, str): values_to_add = [value]
                            elif isinstance(arg_entry, str):
                                values_to_add = [arg_entry]
                            
                            for v in values_to_add:
                                game_args.append(self.replace_arg(v, replacements))
                    
                    if is_modern_fabric:
                        print("[DEBUG] Adicionando argumentos de assets manualmente para o Fabric.")
                        game_args.extend(["--assetsDir", ASSETS_DIR])
                        game_args.extend(["--assetIndex", asset_index])
                
                if is_modern_forge:
                    print("[DEBUG] Adicionando argumentos de jogo manualmente para o Forge Moderno.")
                    game_args.extend(["--username", username])
                    game_args.extend(["--uuid", use_uuid])
                    game_args.extend(["--accessToken", access_token])
                    game_args.extend(["--version", version]) 
                    game_args.extend(["--gameDir", game_dir])
                    game_args.extend(["--assetsDir", ASSETS_DIR])
                    game_args.extend(["--assetIndex", asset_index])
                    game_args.extend(["--userType", "legacy"]) 
            else:
                raise Exception("Formato de JSON desconhecido! Não foi encontrado 'arguments' nem 'minecraftArguments'.")
            
            # --- 9. Montar Comando Final ---
            
            command = [java_exec] + jvm_args + [main_class] + game_args
            command = [arg for arg in command if arg] 
            
            print(f"\n[DEBUG] Argumentos JVM Finais: {' '.join(jvm_args)}\n") 
            print(f"\n[DEBUG] Argumentos de Jogo Finais: {' '.join(game_args)}\n")
            
            self.ui_queue.put({"type": "status", "text": "🚀 Iniciando o jogo..."})
            
            # --- INÍCIO DA NOVA LÓGICA DE INICIALIZAÇÃO ---
            
            show_terminal = self.show_terminal.get()
            creation_flags = 0
            
            if not show_terminal and platform.system().lower() == "windows":
                creation_flags = 0x08000000 
                print("[DEBUG] (BG Thread) Iniciando no Windows sem terminal.")
            else:
                print("[DEBUG] (BG Thread) Iniciando com terminal (Padrão ou não-Windows).")

            # Inicia o jogo A PARTIR DO BACKGROUND THREAD (para não congelar a UI)
            self.game_process = subprocess.Popen(
                command, 
                cwd=GAME_DIR, 
                creationflags=creation_flags
            )

            # Envia a mensagem de sucesso para a UI
            self.ui_queue.put({"type": "status", "text": f"✅ {version} iniciado!", "style": SUCCESS})
            
            # Se a opção de fechar estiver marcada, esta thread fica "viva"
            if self.close_after_launch.get():
                print("[DEBUG] (BG Thread) Escondendo o launcher...")
                self.ui_queue.put({"type": "hide_launcher"}) # Nova mensagem
                
                print("[DEBUG] (BG Thread) Esperando o jogo fechar...")
                self.game_process.wait() # Trava ESTE thread (o de background)
                
                print("[DEBUG] (BG Thread) Jogo fechado. Solicitando reabertura...")
                self.ui_queue.put({"type": "show_launcher"})
            
            # Limpa a referência
            self.game_process = None
            # --- FIM DA NOVA LÓGICA DE INICIALIZAÇÃO ---

        except Exception as e:
            error_message = f"Erro: {e}"
            self.ui_queue.put({"type": "status", "text": error_message, "style": DANGER})
            self.ui_queue.put({"type": "popup_error", "text": error_message})
            print(f"[DEBUG] ERRO FATAL: {e}") 
            import traceback 
            traceback.print_exc() 
        
        finally:
            self.ui_queue.put({"type": "progress_stop"})
            self.ui_queue.put({"type": "button_toggle", "state": "normal"})

# --- Ponto de Entrada da Aplicação ---
if __name__ == "__main__":
    # Garante que a pasta de modpacks (que é do launcher) exista
    os.makedirs(MODPACKS_DIR, exist_ok=True)
    
    # Toda a lógica de GAME_DIR, VERSIONS_DIR, e launcher_profiles.json
    # foi movida para o método _update_paths() dentro da classe.
    
    app = RaposoLauncher()
    app.mainloop()
