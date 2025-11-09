import json
import os
import uuid
import hashlib
import platform

ACCOUNTS_FILE = "accounts.json"


def gerar_uuid_offline(nome: str) -> str:
    nome_hash = hashlib.md5(f"OfflinePlayer:{nome}".encode()).digest()
    bytes_lista = list(nome_hash)
    bytes_lista[6] = (bytes_lista[6] & 0x0F) | 0x30
    bytes_lista[8] = (bytes_lista[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(bytes_lista)))


def carregar_accounts() -> dict:
    if not os.path.exists(ACCOUNTS_FILE):
        return {"accounts": {}, "activeAccount": None}
    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def salvar_accounts(dados: dict):
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=4, ensure_ascii=False)


def limpar_tela():
    if platform.system() == "Windows":
        os.system("cls")
    else:
        os.system("clear")


def adicionar_conta_offline(username: str):
    dados = carregar_accounts()
    uuid_gerado = gerar_uuid_offline(username)
    conta_id = f"offline-{uuid_gerado}"

    dados["accounts"][conta_id] = {
        "username": username,
        "uuid": uuid_gerado,
        "type": "offline"
    }
    dados["activeAccount"] = conta_id
    salvar_accounts(dados)
    print(f"✔ Conta ativa agora: {username} ({uuid_gerado})")


def listar_contas() -> list:
    dados = carregar_accounts()
    return list(dados["accounts"].values())


def escolher_conta():
    limpar_tela()
    dados = carregar_accounts()
    contas = list(dados["accounts"].values())

    if not contas:
        print("Nenhuma conta cadastrada. Criando conta offline padrão...")
        adicionar_conta_offline("PlayerOffline")
        return

    print("\n=== Contas Disponíveis ===")
    for i, c in enumerate(contas, 1):
        print(f"{i} - {c['username']} ({c['uuid']})")

    print("0 - Criar nova conta")
    escolha = input("Escolha uma conta: ").strip()

    if escolha == "0":
        novo_nome = input("Digite o nome da nova conta offline: ").strip()
        if novo_nome:
            adicionar_conta_offline(novo_nome)
    else:
        try:
            idx = int(escolha) - 1
            contas_ids = list(dados["accounts"].keys())
            dados["activeAccount"] = contas_ids[idx]
            salvar_accounts(dados)
            c = dados["accounts"][contas_ids[idx]]
            print(f"✔ Conta ativa agora: {c['username']} ({c['uuid']})")
        except (ValueError, IndexError):
            print("Opção inválida.")


def apagar_conta():
    limpar_tela()
    dados = carregar_accounts()
    contas = list(dados["accounts"].values())

    if not contas:
        print("Nenhuma conta cadastrada.")
        return

    print("\n=== Apagar Conta ===")
    for i, c in enumerate(contas, 1):
        print(f"{i} - {c['username']} ({c['uuid']})")

    escolha = input("Escolha a conta para apagar: ").strip()
    try:
        idx = int(escolha) - 1
        contas_ids = list(dados["accounts"].keys())
        conta_id = contas_ids[idx]
        apagada = dados["accounts"].pop(conta_id)

        if dados.get("activeAccount") == conta_id:
            dados["activeAccount"] = None

        salvar_accounts(dados)
        print(f"✔ Conta apagada: {apagada['username']} ({apagada['uuid']})")
    except (ValueError, IndexError):
        print("Opção inválida.")


def resetar_contas():
    limpar_tela()
    confirmar = input("Tem certeza que deseja resetar todas as contas? (s/n): ").strip().lower()
    if confirmar == "s":
        salvar_accounts({"accounts": {}, "activeAccount": None})
        print("✔ Todas as contas foram resetadas.")
    else:
        print("✖ Reset cancelado.")


def jogar_com_piada(conta):
    limpar_tela()
    # Mensagem divertida
    print(f"Iniciando jogo como {conta['username']} ({conta['uuid']}) (offline)...\n")
    print("Ei, para de ser preguiçoso! Executa o código logo, filho!")
    print("Tá achando que eu vou jogar por você? Execute o comando:")
    print("python main.pyw")
    input("\nPressione qualquer tecla para sair...")


def exibir_menu():
    while True:
        limpar_tela()
        dados = carregar_accounts()
        active_id = dados.get("activeAccount")
        conta = dados["accounts"].get(active_id) if active_id else None

        print("=== Launcher Offline ===")
        if conta:
            print(f"Nome atual: {conta['username']}")
            print(f"UUID atual: {conta['uuid']}")
        else:
            print("Nenhuma conta ativa.")

        print("\n1 - Alterar ou criar conta")
        print("2 - Apagar uma conta")
        print("3 - Resetar todas as contas")
        print("4 - Jogar (usando conta ativa)")
        print("5 - Sair")

        opcao = input("Escolha: ").strip()
        if opcao == "1":
            escolher_conta()
        elif opcao == "2":
            apagar_conta()
        elif opcao == "3":
            resetar_contas()
        elif opcao == "4":
            if not conta:
                print("⚠ Nenhuma conta ativa! Crie ou escolha uma conta primeiro.")
                input("Pressione Enter para continuar...")
                continue
            jogar_com_piada(conta)
            break
        elif opcao == "5":
            print("Saindo do launcher...")
            break
        else:
            print("Opção inválida.")
            input("Pressione Enter para continuar...")


if __name__ == "__main__":
    exibir_menu()
