# -*- coding: utf-8 -*-
"""Diagnosticos amigaveis da LuaStudio: erros de compilacao/runtime e warnings."""

import re

def _line(message):
    m = re.search(r"\(linha\s+(\d+)\)", str(message))
    return int(m.group(1)) if m else None

def explain_compile(message):
    msg = str(message)
    low = msg.lower()
    suggestions = []
    if "string nao fechada" in low:
        title = "String nao fechada"
        fix = "Feche a string com aspas. Exemplo: local nome = \"Nandox\""
    elif "caractere inesperado" in low:
        title = "Caractere inesperado"
        fix = "Remova o caractere ou use a sintaxe Lua correta. Confira parenteses, virgulas, aspas e operadores."
    elif "expressao inesperada" in low:
        title = "Expressao incompleta ou fora do lugar"
        fix = "Verifique o que vem antes e depois dessa linha. Pode estar faltando um operador, valor ou palavra-chave."
    elif "esperado" in low and "encontrado" in low:
        title = "Sintaxe incompleta"
        fix = "A mensagem mostra o simbolo esperado e o encontrado. Confira especialmente end, ), }, ], virgulas e operadores."
    else:
        title = "Erro de compilacao"
        fix = "Revise a sintaxe da linha marcada e tambem a linha imediatamente anterior."
    line = _line(msg)
    return title, fix, line

def explain_runtime(message):
    msg = str(message)
    low = msg.lower()
    rules = [
        (("indexar valor nil", "indice nil"), "Valor nil usado como tabela/objeto",
         "Alguma variavel ou objeto esta nil. Confira se ele foi criado, encontrado ou recebeu um valor antes de usar . ou []."),
        (("chamar um valor do tipo nil", "chamar um valor do tipo boolean", "chamar um valor do tipo number"),
         "Tentativa de chamar algo que nao e funcao",
         "Confira o nome da funcao e se ela realmente existe. Um erro de digitacao pode transformar a funcao em nil."),
        (("aritmetica",), "Operacao matematica com tipo invalido",
         "Confira os valores usados na conta. Nao use nil, texto ou boolean onde a operacao espera numero."),
        (("indice nil na tabela",), "Indice nil em uma tabela",
         "O indice usado para acessar a tabela esta nil. Garanta que a chave tenha um valor antes de usar tabela[chave]."),
        (("limite de execucao atingido",), "Possivel loop infinito",
         "Verifique while/repeat/for e garanta que a condicao ou contador possa terminar."),
        (("modulo", "nao encontrado no projeto"), "Modulo nao encontrado",
         "Confira o nome do arquivo usado em require() e confirme que o .lua esta dentro do projeto."),
        (("dependencia ciclica",), "Dependencia circular em require()",
         "Dois ou mais scripts estao exigindo uns aos outros. Separe a parte compartilhada em um terceiro modulo."),
        (("step igual a zero",), "For numerico com passo zero",
         "Altere o terceiro valor do for para um numero diferente de zero."),
        (("comando desconhecido",), "Comando Lua nao suportado",
         "Confira a sintaxe e se esse recurso pertence ao subconjunto Lua suportado pela LuaStudio."),
    ]
    for needles, title, fix in rules:
        if any(n in low for n in needles):
            return title, fix, _line(msg)
    return "Erro em tempo de execucao", "Revise a linha marcada e os valores usados nela. A mensagem original abaixo ajuda a localizar a causa.", _line(msg)

def warnings(source):
    """Retorna warnings simples e conservadores: (linha, titulo, explicacao)."""
    out = []
    lines = source.splitlines()
    for i, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("--"):
            continue
        if re.search(r"\bwhile\s+true\s+do\b", line):
            out.append((i, "Possivel loop infinito", "while true so termina se houver break ou outra saida controlada."))
        if re.search(r"\brepeat\b", line) and i == len(lines):
            out.append((i, "repeat sem encerramento visivel", "Confira se existe um until correspondente."))
        if re.search(r"\bif\b.*\bthen\b.*\bend\b", line) and re.search(r"\bif\b.*\bif\b", line):
            out.append((i, "Condicao muito compactada", "Separe a logica em linhas para facilitar a leitura e encontrar erros."))
        if re.search(r"\.\.\.\s*\.\.\.", line):
            out.append((i, "Uso suspeito de vararg", "Confira se os operadores de vararg estao realmente sendo usados como pretendido."))
        if re.search(r"\bfunction\s*\([^)]*\)\s*$", line):
            out.append((i, "Funcao sem nome", "Isso cria uma funcao anonima. Tudo bem se for intencional; caso contrario, de um nome a funcao."))
    # Nao avise a mesma linha mais de uma vez.
    seen = set()
    return [x for x in out if not ((x[0], x[1]) in seen or seen.add((x[0], x[1])))]

def format_compile(message):
    title, fix, line = explain_compile(message)
    loc = ("Linha %d. " % line) if line else ""
    return "[ERRO DE COMPILACAO] %s%s\nO que aconteceu: %s\nComo corrigir: %s" % (title, loc, message, fix)

def format_runtime(message):
    title, fix, line = explain_runtime(message)
    loc = ("Linha %d. " % line) if line else ""
    return "[ERRO EM TEMPO DE EXECUCAO] %s%s\nO que aconteceu: %s\nComo corrigir: %s" % (title, loc, message, fix)

def format_warning(line, title, explanation):
    return "[WARNING] Linha %d - %s\n%s" % (line, title, explanation)
