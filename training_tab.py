"""
Aba de Treinamento de IA — SPARTA AGENTE IA
Tema: amarelo/preto (#FFD000 / #0F0F0F), consistente com o restante do sistema.
"""
import json
import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import db

# ── Prompt de extração de aprendizado ─────────────────────────────────────────
_PROMPT_EXTRACAO = (
    "Você é um extrator de dados de calibração para um sistema de vigilância "
    "de garimpo de ouro.\n\n"
    "Com base na conversa abaixo entre o sistema de IA e o operador sobre uma "
    "detecção de câmera, extraia as informações de calibração.\n\n"
    "Detecção original:\n"
    "- Câmera: {camera_id}\n"
    "- Nível detectado: {nivel_risco}\n"
    "- Comportamentos detectados pela IA: {comportamentos}\n"
    "- Ação recomendada: {acao}\n"
    "- Confiança: {confianca}%\n\n"
    "Conversa:\n{conversa}\n\n"
    "Retorne SOMENTE JSON válido, sem texto fora dele:\n"
    '{{\n'
    '  "rotulo": "correto" ou "falso_positivo",\n'
    '  "descricao_real": "o que realmente acontecia (max 180 chars)",\n'
    '  "ajuste_sugerido": "menos_sensivel" ou "mais_sensivel" ou "manter",\n'
    '  "justificativa": "motivo do ajuste de sensibilidade (max 100 chars)",\n'
    '  "observacao": "frase concisa para calibrar exemplos futuros (max 160 chars)"\n'
    '}}\n\n'
    "Regras:\n"
    '- rotulo="correto" se o operador CONFIRMOU suspeita ou furto real\n'
    '- rotulo="falso_positivo" se era comportamento NORMAL de trabalho\n'
    '- ajuste_sugerido="menos_sensivel" se a IA alertou desnecessariamente\n'
    '- ajuste_sugerido="mais_sensivel" se a IA deveria ter alertado mais cedo\n'
    '- ajuste_sugerido="manter" se a sensibilidade parece adequada'
)

# ── Paleta ─────────────────────────────────────────────────────────────────────
BG          = "#050A12"
BG_CARD     = "#08131E"
AMARELO     = "#00D4FF"
AMARELO_ESC = "#007A9E"
BRANCO      = "#C8E8F8"
CINZA       = "#4A6070"
CINZA_ESC   = "#152030"
VERMELHO    = "#FF2255"
VERDE       = "#00CC77"
LARANJA     = "#FF4499"
AZUL        = "#2299FF"

NIVEL_COR = {
    "sem_risco": VERDE,
    "atencao":   AMARELO,
    "suspeito":  LARANJA,
    "critico":   VERMELHO,
}

FONT_TITULO = ("Segoe UI", 13, "bold")
FONT_LABEL  = ("Segoe UI", 9)
FONT_MONO   = ("Consolas", 9)
FONT_BTN    = ("Segoe UI", 9, "bold")
FONT_SMALL  = ("Segoe UI", 8)


def _btn(pai, texto, cmd, bg=AMARELO, fg=BG):
    hover = AMARELO_ESC if bg == AMARELO else (
        "#4a4a4a" if bg == CINZA_ESC else
        "#2eaa60" if bg == VERDE else
        "#cc2222" if bg == VERMELHO else
        "#2e7acc" if bg == AZUL else bg
    )
    b = tk.Label(pai, text=texto, font=FONT_BTN,
                 bg=bg, fg=fg, padx=12, pady=7, cursor="hand2")
    b.bind("<Button-1>", lambda _: cmd())
    b.bind("<Enter>",    lambda _: b.config(bg=hover))
    b.bind("<Leave>",    lambda _: b.config(bg=bg))
    return b


# ── Diálogo de Chat com IA ─────────────────────────────────────────────────────

class ChatDialog:
    """
    Conversa com a IA sobre uma análise específica.
    O operador explica o que realmente acontecia na cena.
    Ao clicar em "Aprender", Claude extrai aprendizado estruturado da conversa
    e o sistema ajusta calibração imediatamente — sem que o operador precise
    saber nada sobre parâmetros técnicos.
    """

    _SYSTEM = (
        "Você é o assistente de calibração do SPARTA AGENTE IA, sistema de vigilância "
        "para garimpo de ouro. Ajude o operador a explicar o que realmente aconteceu "
        "na cena detectada. Faça perguntas curtas e objetivas. "
        "Responda em português brasileiro. Seja conciso."
    )

    def __init__(self, parent: tk.Misc, analise: dict,
                 on_aprendizado=None, on_salvar_obs=None):
        self._on_aprendizado = on_aprendizado
        self._on_salvar_obs  = on_salvar_obs   # mantido para compat.
        self._historico: list[dict] = []
        self._analise = analise
        self._dados_extraidos: dict | None = None

        self._win = tk.Toplevel(parent)
        self._win.title("Conversar com IA — Explicar Ocorrência")
        self._win.configure(bg=BG)
        self._win.geometry("700x580")
        self._win.resizable(True, True)
        self._win.grab_set()
        self._win.attributes("-topmost", True)

        self._montar_ui()
        self._mensagem_inicial()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _montar_ui(self):
        a = self._analise
        comps = json.loads(a["comportamentos"]) if a.get("comportamentos") else []
        resumo = (
            f"Câmera: {a.get('camera_id','?')}  |  "
            f"{str(a.get('timestamp_analise',''))[:19]}  |  "
            f"Nível: {a.get('nivel_risco','?').upper()}  |  "
            f"Confiança: {a.get('confianca',0)*100:.0f}%"
        )

        # Cabeçalho
        cab = tk.Frame(self._win, bg=AMARELO, padx=16, pady=8)
        cab.pack(fill="x")
        tk.Label(cab, text="Conversar com IA — Ensinar o Sistema",
                 font=("Segoe UI", 10, "bold"), bg=AMARELO, fg=BG).pack(side="left")

        # Contexto
        ctx = tk.Frame(self._win, bg=BG_CARD, padx=14, pady=8)
        ctx.pack(fill="x")
        tk.Label(ctx, text=resumo, font=FONT_MONO, bg=BG_CARD, fg=CINZA).pack(anchor="w")
        if comps:
            desc = " | ".join(comps[:2]) + ("..." if len(comps) > 2 else "")
            tk.Label(ctx, text=f"Detectado: {desc}", font=FONT_SMALL,
                     bg=BG_CARD, fg=BRANCO, wraplength=660, justify="left").pack(anchor="w")

        # Histórico do chat
        frm_hist = tk.Frame(self._win, bg=BG)
        frm_hist.pack(fill="both", expand=True, padx=10, pady=(8, 0))

        self._txt_hist = tk.Text(
            frm_hist, bg="#060D16", fg=BRANCO, font=("Segoe UI", 9),
            wrap="word", state="disabled", relief="flat",
            highlightthickness=1, highlightbackground=CINZA_ESC,
            spacing1=4, spacing3=4,
        )
        sb_hist = ttk.Scrollbar(frm_hist, orient="vertical",
                                command=self._txt_hist.yview)
        self._txt_hist.configure(yscrollcommand=sb_hist.set)
        sb_hist.pack(side="right", fill="y")
        self._txt_hist.pack(fill="both", expand=True)

        self._txt_hist.tag_configure("ia",     foreground=AMARELO, font=("Segoe UI", 9, "bold"))
        self._txt_hist.tag_configure("vc",     foreground=VERDE,   font=("Segoe UI", 9, "bold"))
        self._txt_hist.tag_configure("msg",    foreground=BRANCO,  font=("Segoe UI", 9))
        self._txt_hist.tag_configure("status", foreground=CINZA,   font=("Segoe UI", 8, "italic"))

        # Área de digitação
        frm_input = tk.Frame(self._win, bg=BG_CARD, padx=10, pady=8)
        frm_input.pack(fill="x", padx=10, pady=(4, 0))

        self._txt_input = tk.Text(
            frm_input, bg="#0C1825", fg=BRANCO, font=("Segoe UI", 9),
            height=3, wrap="word", relief="flat",
            insertbackground=AMARELO,
            highlightthickness=1, highlightbackground=CINZA_ESC,
        )
        self._txt_input.pack(fill="x")
        self._txt_input.bind("<Return>", self._on_enter)
        self._txt_input.bind("<Shift-Return>", lambda e: None)

        # Barra de botões
        frm_btns = tk.Frame(self._win, bg=BG, padx=10, pady=8)
        frm_btns.pack(fill="x")

        _btn(frm_btns, "  Enviar  ", self._enviar,
             bg=AMARELO, fg=BG).pack(side="left")
        tk.Label(frm_btns, text="Enter envia  |  Shift+Enter nova linha",
                 font=FONT_SMALL, bg=BG, fg=CINZA).pack(side="left", padx=10)

        self._sv_status = tk.StringVar(value="")
        tk.Label(frm_btns, textvariable=self._sv_status,
                 font=FONT_SMALL, bg=BG, fg=CINZA).pack(side="left", padx=4)

        # Botão "Aprender" — aparece após 1ª resposta da IA
        self._btn_aprender = _btn(frm_btns, "  Aprender com esta Conversa ▶  ",
                                  self._aprender, bg=VERDE, fg=BG)
        self._btn_aprender.pack(side="right", padx=(0, 4))
        self._btn_aprender.pack_forget()

        _btn(frm_btns, "  Fechar  ", self._win.destroy,
             bg=CINZA_ESC, fg=BRANCO).pack(side="right", padx=(0, 6))

    # ── Chat ──────────────────────────────────────────────────────────────────

    def _mensagem_inicial(self):
        a = self._analise
        comps = json.loads(a["comportamentos"]) if a.get("comportamentos") else []
        nivel = a.get("nivel_risco", "atencao").upper()

        msg_ia = (
            f"Analisei esta cena e classifiquei como {nivel} "
            f"com {a.get('confianca',0)*100:.0f}% de confiança.\n\n"
            "Comportamentos que identifiquei:\n" +
            "\n".join(f"• {c}" for c in comps) +
            "\n\nO que realmente estava acontecendo neste momento? "
            "Descreva com suas próprias palavras — qualquer detalhe ajuda o sistema a aprender."
        )
        self._adicionar_mensagem("IA", msg_ia)
        self._historico.append({"role": "assistant", "content": msg_ia})

    def _on_enter(self, event):
        if not (event.state & 0x1):
            self._enviar()
            return "break"

    def _enviar(self):
        texto = self._txt_input.get("1.0", "end-1c").strip()
        if not texto:
            return
        self._txt_input.delete("1.0", "end")
        self._adicionar_mensagem("Você", texto)
        self._historico.append({"role": "user", "content": texto})
        self._sv_status.set("Aguardando IA...")
        threading.Thread(target=self._chamar_ia, daemon=True).start()

    def _chamar_ia(self):
        try:
            from config import CLAUDE_API_KEY
            import anthropic as _ant
            client = _ant.Anthropic(api_key=CLAUDE_API_KEY)

            a = self._analise
            comps = json.loads(a["comportamentos"]) if a.get("comportamentos") else []
            contexto = (
                f"Câmera={a.get('camera_id')}, nível={a.get('nivel_risco')}, "
                f"confiança={a.get('confianca',0)*100:.0f}%, "
                f"comportamentos: {'; '.join(comps)}, "
                f"ação: {a.get('acao_recomendada','N/A')}"
            )
            system = f"{self._SYSTEM}\n\nContexto da análise:\n{contexto}"

            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                system=system,
                messages=self._historico,
            )
            resposta = resp.content[0].text
            self._historico.append({"role": "assistant", "content": resposta})
            self._win.after(0, lambda: self._adicionar_mensagem("IA", resposta))
            self._win.after(0, lambda: self._sv_status.set(""))
            self._win.after(0, lambda: self._btn_aprender.pack(side="right", padx=(0, 4)))
        except Exception as exc:
            self._win.after(0, lambda: self._adicionar_mensagem(
                "IA", f"[Erro ao conectar: {exc}]"))
            self._win.after(0, lambda: self._sv_status.set(""))

    def _adicionar_mensagem(self, remetente: str, texto: str):
        self._txt_hist.configure(state="normal")
        tag = "ia" if remetente == "IA" else "vc"
        self._txt_hist.insert("end", f"{remetente}:\n", tag)
        self._txt_hist.insert("end", f"{texto}\n\n", "msg")
        self._txt_hist.configure(state="disabled")
        self._txt_hist.see("end")

    # ── Extração de aprendizado ───────────────────────────────────────────────

    def _aprender(self):
        """Inicia extração estruturada do aprendizado via Claude Haiku."""
        n_trocas = sum(1 for m in self._historico if m["role"] == "user")
        if n_trocas == 0:
            self._sv_status.set("Explique a situação para a IA antes de aprender.")
            return
        self._btn_aprender.config(text="  Extraindo aprendizado...  ")
        self._sv_status.set("")
        threading.Thread(target=self._extrair_e_mostrar, daemon=True).start()

    def _extrair_e_mostrar(self):
        try:
            dados = self._extrair_aprendizado()
            self._win.after(0, lambda: self._mostrar_confirmacao(dados))
        except Exception as exc:
            self._win.after(0, lambda: self._sv_status.set(f"Erro na extração: {exc}"))
            self._win.after(0, lambda: self._btn_aprender.config(
                text="  Aprender com esta Conversa ▶  "))

    def _extrair_aprendizado(self) -> dict:
        from config import CLAUDE_API_KEY
        import anthropic as _ant

        a = self._analise
        comps = json.loads(a["comportamentos"]) if a.get("comportamentos") else []
        conversa = "\n".join(
            f"{'IA' if m['role'] == 'assistant' else 'Operador'}: {m['content']}"
            for m in self._historico
        )
        prompt = _PROMPT_EXTRACAO.format(
            camera_id=a.get("camera_id", "?"),
            nivel_risco=a.get("nivel_risco", "?"),
            comportamentos="; ".join(comps) or "nenhum",
            acao=a.get("acao_recomendada", "N/A"),
            confianca=f"{a.get('confianca', 0) * 100:.0f}",
            conversa=conversa,
        )
        client = _ant.Anthropic(api_key=CLAUDE_API_KEY)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        # Remove markdown se presente
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE).strip()
        return json.loads(text)

    def _mostrar_confirmacao(self, dados: dict):
        """Exibe painel de confirmação com os dados extraídos."""
        self._dados_extraidos = dados

        dlg = tk.Toplevel(self._win)
        dlg.title("Confirmar Aprendizado")
        dlg.configure(bg=BG)
        dlg.geometry("520x380")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.attributes("-topmost", True)

        rotulo_ex = dados.get("rotulo", "falso_positivo")
        ajuste_ex = dados.get("ajuste_sugerido", "manter")
        desc_ex   = dados.get("descricao_real", "")
        just_ex   = dados.get("justificativa", "")
        obs_ex    = dados.get("observacao", "")

        # Cabeçalho
        cor_cab = VERDE if rotulo_ex == "correto" else VERMELHO
        label_rot = "ALERTA CORRETO" if rotulo_ex == "correto" else "FALSO POSITIVO"
        cab = tk.Frame(dlg, bg=cor_cab, padx=16, pady=10)
        cab.pack(fill="x")
        tk.Label(cab, text=f"Aprendizado extraído — {label_rot}",
                 font=("Segoe UI", 10, "bold"), bg=cor_cab, fg=BG).pack(side="left")

        body = tk.Frame(dlg, bg=BG, padx=18, pady=14)
        body.pack(fill="both", expand=True)

        def _linha(label, valor, cor=BRANCO):
            f = tk.Frame(body, bg=BG)
            f.pack(fill="x", pady=3)
            tk.Label(f, text=f"{label}:", font=FONT_SMALL, bg=BG, fg=CINZA,
                     width=22, anchor="w").pack(side="left")
            tk.Label(f, text=valor, font=FONT_LABEL, bg=BG, fg=cor,
                     wraplength=320, justify="left", anchor="w").pack(side="left", fill="x")

        _linha("O que acontecia",   desc_ex or "—")
        _linha("Classificação",     label_rot,
               VERDE if rotulo_ex == "correto" else VERMELHO)
        _cor_ajuste = CINZA if ajuste_ex == "manter" else (AZUL if ajuste_ex == "mais_sensivel" else LARANJA)
        _label_ajuste = {
            "manter":         "Manter sensibilidade atual",
            "menos_sensivel": "Reduzir sensibilidade (menos alarmes)",
            "mais_sensivel":  "Aumentar sensibilidade (detectar mais)",
        }.get(ajuste_ex, ajuste_ex)
        _linha("Ajuste de sensibilidade", _label_ajuste, _cor_ajuste)
        if just_ex:
            _linha("Motivo",          just_ex, CINZA)
        if obs_ex:
            _linha("Obs. p/ calibração", obs_ex)

        # Override de rótulo (caso extração tenha errado)
        tk.Frame(body, bg=CINZA_ESC, height=1).pack(fill="x", pady=(10, 6))
        tk.Label(body, text="A classificação está errada? Corrija antes de confirmar:",
                 font=FONT_SMALL, bg=BG, fg=CINZA).pack(anchor="w")

        frm_ov = tk.Frame(body, bg=BG)
        frm_ov.pack(fill="x", pady=4)
        sv_rotulo = tk.StringVar(value=rotulo_ex)
        tk.Radiobutton(frm_ov, text="Alerta Correto",  variable=sv_rotulo,
                       value="correto",         bg=BG, fg=VERDE,
                       selectcolor=BG, font=FONT_SMALL).pack(side="left", padx=(0, 12))
        tk.Radiobutton(frm_ov, text="Falso Positivo",  variable=sv_rotulo,
                       value="falso_positivo",  bg=BG, fg=VERMELHO,
                       selectcolor=BG, font=FONT_SMALL).pack(side="left")

        # Botões de confirmação
        tk.Frame(body, bg=CINZA_ESC, height=1).pack(fill="x", pady=(10, 6))
        frm_ok = tk.Frame(body, bg=BG)
        frm_ok.pack(fill="x")

        def _confirmar():
            dados["rotulo"] = sv_rotulo.get()
            dlg.destroy()
            self._aplicar_aprendizado(dados)

        _btn(frm_ok, "  Confirmar e Aplicar  ", _confirmar,
             bg=VERDE, fg=BG).pack(side="left")
        _btn(frm_ok, "  Cancelar  ", dlg.destroy,
             bg=CINZA_ESC, fg=BRANCO).pack(side="left", padx=(8, 0))

    def _aplicar_aprendizado(self, dados: dict):
        """Chama o callback e fecha o diálogo."""
        if self._on_aprendizado:
            self._on_aprendizado(dados)
        # Compat: popula on_salvar_obs com observação concisa
        if self._on_salvar_obs and dados.get("observacao"):
            self._on_salvar_obs(dados["observacao"])
        self._win.destroy()


# ── Player de Vídeo ────────────────────────────────────────────────────────────

class VideoPlayerDialog:
    """Janela para visualizar o clipe de vídeo capturado durante um alerta."""

    def __init__(self, parent: tk.Misc, analise: dict,
                 on_salvar=None, on_descartar=None):
        self._analise      = analise
        self._on_salvar    = on_salvar
        self._on_descartar = on_descartar
        self._clip_path    = analise.get("clip_path", "")
        self._frames: list = []
        self._idx          = 0
        self._playing      = False
        self._photo        = None
        self._after_id     = None
        self._frame_ms     = 33

        self._win = tk.Toplevel(parent)
        self._win.title("▶ Clipe de Alerta — SPARTA")
        self._win.configure(bg=BG)
        self._win.geometry("720x580")
        self._win.resizable(True, True)
        self._win.grab_set()
        self._win.protocol("WM_DELETE_WINDOW", self._fechar)

        self._montar_ui()
        self._carregar_video()

    def _montar_ui(self):
        a = self._analise
        resumo = (
            f"Câmera: {a.get('camera_id','?')}  |  "
            f"{str(a.get('timestamp_analise',''))[:19]}  |  "
            f"Nível: {a.get('nivel_risco','?').upper()}  |  "
            f"Conf: {a.get('confianca',0)*100:.0f}%"
        )

        cab = tk.Frame(self._win, bg=LARANJA, padx=16, pady=8)
        cab.pack(fill="x")
        tk.Label(cab, text="▶  Clipe de Alerta Detectado",
                 font=("Segoe UI", 10, "bold"), bg=LARANJA, fg=BRANCO).pack(side="left")

        ctx = tk.Frame(self._win, bg=BG_CARD, padx=14, pady=6)
        ctx.pack(fill="x")
        tk.Label(ctx, text=resumo, font=FONT_MONO, bg=BG_CARD, fg=CINZA).pack(anchor="w")

        self._canvas = tk.Canvas(self._win, bg="#000000", highlightthickness=0)
        self._canvas.pack(fill="both", expand=True, padx=8, pady=(6, 2))

        self._var_pos = tk.IntVar(value=0)
        self._scale = tk.Scale(
            self._win, from_=0, to=0, orient="horizontal",
            variable=self._var_pos, command=self._seek,
            bg=BG, fg=BRANCO, troughcolor=CINZA_ESC,
            highlightthickness=0, sliderrelief="flat", sliderlength=12,
        )
        self._scale.pack(fill="x", padx=8)

        self._sv_pos = tk.StringVar(value="0 / 0")
        tk.Label(self._win, textvariable=self._sv_pos,
                 font=FONT_SMALL, bg=BG, fg=CINZA).pack()

        ctrl = tk.Frame(self._win, bg=BG, pady=4)
        ctrl.pack()
        _btn(ctrl, "⏮", self._ir_inicio, bg=CINZA_ESC, fg=BRANCO).pack(side="left", padx=2)
        self._btn_play = _btn(ctrl, "▶ Play", self._toggle_play, bg=AMARELO, fg=BG)
        self._btn_play.pack(side="left", padx=4)
        _btn(ctrl, "⏭", self._ir_fim, bg=CINZA_ESC, fg=BRANCO).pack(side="left", padx=2)

        tk.Frame(self._win, bg=CINZA_ESC, height=1).pack(fill="x", padx=8, pady=(8, 4))
        dec = tk.Frame(self._win, bg=BG, pady=6)
        dec.pack(fill="x", padx=8)
        tk.Label(dec, text="O que deseja fazer com este clipe?",
                 font=FONT_LABEL, bg=BG, fg=CINZA).pack(side="left", padx=(0, 12))
        _btn(dec, "  Salvar localmente  ", self._salvar_local,
             bg=VERDE, fg=BG).pack(side="left", padx=(0, 4))
        _btn(dec, "  Descartar clipe  ", self._descartar,
             bg=VERMELHO, fg=BRANCO).pack(side="left", padx=(0, 4))
        _btn(dec, "  Fechar (manter)  ", self._fechar,
             bg=CINZA_ESC, fg=BRANCO).pack(side="left")

    def _carregar_video(self):
        import cv2 as _cv2
        try:
            cap = _cv2.VideoCapture(self._clip_path)
            if not cap.isOpened():
                self._mostrar_erro("Arquivo de vídeo não encontrado ou corrompido.")
                return
            fps = cap.get(_cv2.CAP_PROP_FPS) or 25
            self._frame_ms = max(15, int(1000 / fps))
            self._frames = []
            while True:
                ok, fr = cap.read()
                if not ok:
                    break
                self._frames.append(fr)
            cap.release()
            if not self._frames:
                self._mostrar_erro("Vídeo vazio ou formato não suportado.")
                return
            total = len(self._frames)
            self._scale.configure(to=max(0, total - 1))
            self._sv_pos.set(f"0 / {total}")
            self._mostrar_frame(0)
        except Exception as exc:
            self._mostrar_erro(f"Erro ao abrir vídeo: {exc}")

    def _mostrar_erro(self, msg: str):
        self._canvas.create_text(
            360, 120, text=msg, fill=VERMELHO,
            font=("Segoe UI", 11), anchor="center",
        )

    def _mostrar_frame(self, idx: int):
        if not self._frames or idx < 0 or idx >= len(self._frames):
            return
        import cv2 as _cv2
        from PIL import Image as _PilImg, ImageTk as _ITk
        fr = self._frames[idx]
        cw = self._canvas.winfo_width()  or 640
        ch = self._canvas.winfo_height() or 360
        fh, fw = fr.shape[:2]
        escala = min(cw / fw, ch / fh, 1.0)
        nw = max(1, int(fw * escala))
        nh = max(1, int(fh * escala))
        resized = _cv2.resize(fr, (nw, nh))
        rgb = _cv2.cvtColor(resized, _cv2.COLOR_BGR2RGB)
        self._photo = _ITk.PhotoImage(image=_PilImg.fromarray(rgb))
        self._canvas.delete("all")
        self._canvas.create_image(cw // 2, ch // 2, image=self._photo, anchor="center")
        self._sv_pos.set(f"{idx + 1} / {len(self._frames)}")
        self._var_pos.set(idx)

    def _next_frame(self):
        if not self._playing:
            return
        self._idx = (self._idx + 1) % max(1, len(self._frames))
        self._mostrar_frame(self._idx)
        self._after_id = self._win.after(self._frame_ms, self._next_frame)

    def _toggle_play(self):
        if not self._frames:
            return
        self._playing = not self._playing
        if self._playing:
            self._btn_play.config(text="⏸ Pausa")
            self._next_frame()
        else:
            self._btn_play.config(text="▶ Play")
            if self._after_id:
                self._win.after_cancel(self._after_id)

    def _seek(self, val):
        try:
            self._idx = int(float(val))
            self._mostrar_frame(self._idx)
        except Exception:
            pass

    def _ir_inicio(self):
        self._playing = False
        self._btn_play.config(text="▶ Play")
        if self._after_id:
            self._win.after_cancel(self._after_id)
        self._idx = 0
        self._mostrar_frame(0)

    def _ir_fim(self):
        self._playing = False
        self._btn_play.config(text="▶ Play")
        if self._after_id:
            self._win.after_cancel(self._after_id)
        if self._frames:
            self._idx = len(self._frames) - 1
            self._mostrar_frame(self._idx)

    def _salvar_local(self):
        from tkinter import filedialog
        import shutil
        dest = filedialog.asksaveasfilename(
            defaultextension=".mp4",
            filetypes=[("Vídeo MP4", "*.mp4")],
            title="Salvar clipe de alerta",
            initialfile=f"alerta_{self._analise.get('frame_id','clip')}.mp4",
        )
        if not dest:
            return
        try:
            shutil.copy2(self._clip_path, dest)
            if self._on_salvar:
                self._on_salvar(dest)
            self._fechar()
        except Exception as exc:
            from tkinter import messagebox
            messagebox.showerror("Erro", f"Não foi possível salvar:\n{exc}",
                                 parent=self._win)

    def _descartar(self):
        from tkinter import messagebox
        if not messagebox.askyesno(
            "Descartar clipe",
            "Deletar o vídeo permanentemente?\nEsta ação não pode ser desfeita.",
            parent=self._win,
        ):
            return
        self._playing = False
        if self._after_id:
            self._win.after_cancel(self._after_id)
        if self._on_descartar:
            self._on_descartar()
        self._win.destroy()

    def _fechar(self):
        self._playing = False
        if self._after_id:
            self._win.after_cancel(self._after_id)
        self._win.destroy()


# ── TrainingTab ────────────────────────────────────────────────────────────────

class TrainingTab:
    def __init__(self, root: tk.Tk):
        self._root = root
        self._analise_selecionada = None
        self._filtro_nivel        = tk.StringVar(value="todos")
        self._filtro_camera       = tk.StringVar(value="todas")
        self._filtro_data_inicio  = tk.StringVar(value="")
        self._filtro_data_fim     = tk.StringVar(value="")

        root.title("SPARTA AGENTE IA — Treinamento de IA")
        root.configure(bg=BG)
        root.geometry("1100x720")
        root.minsize(900, 580)

        self._montar_cabecalho()
        self._montar_corpo()
        self._carregar_dados()

    # ── Cabecalho ──────────────────────────────────────────────────────────────

    def _montar_cabecalho(self):
        cab = tk.Frame(self._root, bg=AMARELO, padx=20, pady=10)
        cab.pack(fill="x")
        tk.Label(cab, text="SPARTA AGENTE IA  —  Treinamento de IA",
                 font=FONT_TITULO, bg=AMARELO, fg=BG).pack(side="left")

        self._sv_badge = tk.StringVar(value="")
        self._lbl_badge = tk.Label(cab, textvariable=self._sv_badge,
                                   font=FONT_BTN, bg=VERMELHO, fg=BRANCO,
                                   padx=10, pady=3)

    # ── Corpo ──────────────────────────────────────────────────────────────────

    def _montar_corpo(self):
        topo = tk.Frame(self._root, bg=BG_CARD, padx=16, pady=10)
        topo.pack(fill="x")
        self._montar_filtros(topo)
        self._montar_estatisticas_resumidas(topo)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=CINZA_ESC, foreground=BRANCO,
                        padding=[14, 6], font=FONT_LABEL)
        style.map("TNotebook.Tab",
                  background=[("selected", AMARELO)],
                  foreground=[("selected", BG)])
        style.configure("Treeview", background=BG_CARD, foreground=BRANCO,
                        fieldbackground=BG_CARD, rowheight=22)
        style.configure("Treeview.Heading", background=CINZA_ESC,
                        foreground=BRANCO, font=FONT_LABEL)
        style.map("Treeview", background=[("selected", AMARELO_ESC)])

        self._nb = ttk.Notebook(self._root)
        self._nb.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        aba1 = tk.Frame(self._nb, bg=BG)
        self._nb.add(aba1, text="  Detecções  ")
        self._montar_aba_deteccoes(aba1)

        aba2 = tk.Frame(self._nb, bg=BG)
        self._nb.add(aba2, text="  Perguntas (0)  ")
        self._aba2 = aba2
        self._montar_aba_perguntas(aba2)

        aba3 = tk.Frame(self._nb, bg=BG)
        self._nb.add(aba3, text="  Estatísticas  ")
        self._montar_aba_estatisticas(aba3)

        aba4 = tk.Frame(self._nb, bg=BG)
        self._nb.add(aba4, text="  Tokens  ")
        self._montar_aba_tokens(aba4)

        aba5 = tk.Frame(self._nb, bg=BG)
        self._nb.add(aba5, text="  Tendências  ")
        self._montar_aba_tendencias(aba5)

    def _montar_filtros(self, pai):
        f = tk.Frame(pai, bg=BG_CARD)
        f.pack(side="left")

        tk.Label(f, text="FILTROS", font=("Segoe UI", 8, "bold"),
                 bg=BG_CARD, fg=AMARELO).pack(anchor="w")

        row1 = tk.Frame(f, bg=BG_CARD)
        row1.pack(fill="x", pady=2)

        tk.Label(row1, text="Nível:", font=FONT_LABEL,
                 bg=BG_CARD, fg=CINZA).pack(side="left")
        ttk.Combobox(row1, textvariable=self._filtro_nivel, width=11, state="readonly",
                     values=["todos", "sem_risco", "atencao", "suspeito", "critico"]
                     ).pack(side="left", padx=(4, 12))

        tk.Label(row1, text="Câmera:", font=FONT_LABEL,
                 bg=BG_CARD, fg=CINZA).pack(side="left")
        self._cb_camera = ttk.Combobox(row1, textvariable=self._filtro_camera,
                                       width=13, state="readonly")
        self._cb_camera.pack(side="left", padx=(4, 0))

        row2 = tk.Frame(f, bg=BG_CARD)
        row2.pack(fill="x", pady=2)

        tk.Label(row2, text="De:", font=FONT_LABEL, bg=BG_CARD, fg=CINZA).pack(side="left")
        tk.Entry(row2, textvariable=self._filtro_data_inicio, font=FONT_MONO,
                 bg="#0C1825", fg=BRANCO, insertbackground=AMARELO,
                 relief="flat", width=11).pack(side="left", padx=(4, 8))
        tk.Label(row2, text="Até:", font=FONT_LABEL, bg=BG_CARD, fg=CINZA).pack(side="left")
        tk.Entry(row2, textvariable=self._filtro_data_fim, font=FONT_MONO,
                 bg="#0C1825", fg=BRANCO, insertbackground=AMARELO,
                 relief="flat", width=11).pack(side="left", padx=(4, 0))
        tk.Label(row2, text="(AAAA-MM-DD)", font=FONT_SMALL,
                 bg=BG_CARD, fg=CINZA).pack(side="left", padx=(6, 0))

        brow = tk.Frame(f, bg=BG_CARD)
        brow.pack(anchor="w", pady=(6, 0))
        _btn(brow, " Filtrar ", self._carregar_dados).pack(side="left")
        _btn(brow, " Exportar Excel ", self._exportar_excel,
             bg=CINZA_ESC, fg=BRANCO).pack(side="left", padx=(8, 0))

    def _montar_estatisticas_resumidas(self, pai):
        f = tk.Frame(pai, bg=BG_CARD, padx=24)
        f.pack(side="right", anchor="ne")
        tk.Label(f, text="RESUMO", font=("Segoe UI", 8, "bold"),
                 bg=BG_CARD, fg=AMARELO).pack(anchor="w")
        self._sv_resumo = tk.StringVar(value="Carregando...")
        tk.Label(f, textvariable=self._sv_resumo, font=FONT_MONO,
                 bg=BG_CARD, fg=BRANCO, justify="left").pack(anchor="w")

    # ── Aba 1: Detecções ───────────────────────────────────────────────────────

    def _montar_aba_deteccoes(self, pai):
        cols = ("hora", "camera", "nivel", "confianca", "feedback")
        self._tree = ttk.Treeview(pai, columns=cols, show="headings", height=14)

        for col, larg, anc in [
            ("hora",      145, "w"),
            ("camera",    130, "w"),
            ("nivel",     110, "center"),
            ("confianca",  80, "center"),
            ("feedback",   90, "center"),
        ]:
            self._tree.heading(col, text=col.capitalize())
            self._tree.column(col, width=larg, anchor=anc)

        self._tree.tag_configure("sem_risco", foreground=VERDE)
        self._tree.tag_configure("atencao",   foreground=AMARELO)
        self._tree.tag_configure("suspeito",  foreground=LARANJA)
        self._tree.tag_configure("critico",   foreground=VERMELHO,
                                 font=("Segoe UI", 9, "bold"))

        sb = ttk.Scrollbar(pai, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        sb.pack(side="left", fill="y", pady=8)
        self._tree.bind("<<TreeviewSelect>>", self._on_selecionar)

        # Painel de detalhes + feedback
        painel = tk.Frame(pai, bg=BG_CARD, padx=16, pady=14, width=320)
        painel.pack(side="left", fill="y", padx=8, pady=8)
        painel.pack_propagate(False)

        tk.Label(painel, text="DETALHES", font=("Segoe UI", 8, "bold"),
                 bg=BG_CARD, fg=AMARELO).pack(anchor="w")

        self._sv_detalhe = tk.StringVar(value="Selecione uma deteccao")
        tk.Label(painel, textvariable=self._sv_detalhe, font=FONT_MONO,
                 bg=BG_CARD, fg=BRANCO, wraplength=270,
                 justify="left").pack(anchor="w", pady=(4, 12))

        tk.Frame(painel, bg=CINZA_ESC, height=1).pack(fill="x", pady=(0, 10))

        tk.Label(painel, text="FEEDBACK DO ADMIN", font=("Segoe UI", 8, "bold"),
                 bg=BG_CARD, fg=AMARELO).pack(anchor="w")

        brow = tk.Frame(painel, bg=BG_CARD)
        brow.pack(fill="x", pady=6)
        _btn(brow, "Correto", lambda: self._salvar_feedback("correto"),
             bg=VERDE, fg=BG).pack(side="left", expand=True, fill="x", padx=(0, 4))
        _btn(brow, "Falso Positivo", lambda: self._salvar_feedback("falso_positivo"),
             bg=VERMELHO, fg=BRANCO).pack(side="left", expand=True, fill="x")

        # Botão de chat com IA
        _btn(painel, "  Conversar com IA sobre esta ocorrência  ",
             self._abrir_chat, bg=AZUL, fg=BRANCO).pack(fill="x", pady=(2, 4))

        # Botão de player de vídeo (visível somente quando clip existe em disco)
        self._btn_clip = _btn(painel, "  ▶ Ver Clipe do Alerta  ",
                              self._abrir_player, bg=LARANJA, fg=BRANCO)

        tk.Frame(painel, bg=CINZA_ESC, height=1).pack(fill="x", pady=(8, 8))

        tk.Label(painel, text="Observação / Explicação:",
                 font=FONT_LABEL, bg=BG_CARD, fg=CINZA).pack(anchor="w", pady=(0, 2))
        tk.Label(painel,
                 text="Descreva o que realmente acontecia na cena.",
                 font=FONT_SMALL, bg=BG_CARD, fg=CINZA, wraplength=270,
                 justify="left").pack(anchor="w", pady=(0, 4))

        # Campo de texto multi-linha para observação
        frm_obs = tk.Frame(painel, bg=BG_CARD)
        frm_obs.pack(fill="x")
        self._text_obs = tk.Text(
            frm_obs, font=FONT_MONO, bg="#0C1825", fg=BRANCO,
            insertbackground=AMARELO, relief="flat",
            highlightthickness=1, highlightbackground=CINZA_ESC,
            height=4, wrap="word",
        )
        sb_obs = ttk.Scrollbar(frm_obs, orient="vertical",
                               command=self._text_obs.yview)
        self._text_obs.configure(yscrollcommand=sb_obs.set)
        sb_obs.pack(side="right", fill="y")
        self._text_obs.pack(fill="x")

        self._sv_fb_status = tk.StringVar(value="")
        tk.Label(painel, textvariable=self._sv_fb_status,
                 font=FONT_LABEL, bg=BG_CARD, fg=VERDE).pack(anchor="w", pady=(5, 0))

        tk.Frame(painel, bg=CINZA_ESC, height=1).pack(fill="x", pady=(10, 8))
        tk.Label(painel, text="DICA", font=("Segoe UI", 8, "bold"),
                 bg=BG_CARD, fg=AMARELO).pack(anchor="w")
        tk.Label(painel,
                 text="Use o chat para explicar o contexto\nda ocorrência. A observação salva\nenriquece o exemplo few-shot e\nmelhora a precisão da IA.",
                 font=FONT_SMALL, bg=BG_CARD, fg=CINZA, justify="left").pack(anchor="w")

    # ── Aba 2: Perguntas ───────────────────────────────────────────────────────

    def _montar_aba_perguntas(self, pai):
        canvas = tk.Canvas(pai, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(pai, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True)

        self._frame_perguntas = tk.Frame(canvas, bg=BG)
        win = canvas.create_window((0, 0), window=self._frame_perguntas, anchor="nw")

        def _cfg(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(win, width=canvas.winfo_width())

        self._frame_perguntas.bind("<Configure>", _cfg)
        canvas.bind("<Configure>", _cfg)

    # ── Aba 3: Estatísticas ────────────────────────────────────────────────────

    def _montar_aba_estatisticas(self, pai):
        f = tk.Frame(pai, bg=BG, padx=28, pady=24)
        f.pack(fill="both", expand=True)
        tk.Label(f, text="METRICAS DE DESEMPENHO DA IA",
                 font=("Segoe UI", 11, "bold"), bg=BG, fg=AMARELO).pack(anchor="w", pady=(0, 16))
        self._sv_stats_full = tk.StringVar(value="")
        tk.Label(f, textvariable=self._sv_stats_full, font=("Consolas", 10),
                 bg=BG, fg=BRANCO, justify="left").pack(anchor="w")

    # ── Aba 4: Tokens ──────────────────────────────────────────────────────────

    def _montar_aba_tokens(self, pai):
        f = tk.Frame(pai, bg=BG, padx=28, pady=24)
        f.pack(fill="both", expand=True)
        tk.Label(f, text="USO DE TOKENS — ÚLTIMOS 30 DIAS",
                 font=("Segoe UI", 11, "bold"), bg=BG, fg=AMARELO).pack(anchor="w", pady=(0, 12))
        self._sv_tokens = tk.StringVar(value="Carregando...")
        tk.Label(f, textvariable=self._sv_tokens, font=("Consolas", 9),
                 bg=BG, fg=BRANCO, justify="left").pack(anchor="w")

    def _atualizar_aba_tokens(self):
        try:
            dados = db.estatisticas_tokens(dias=30)
        except Exception:
            self._sv_tokens.set("Erro ao carregar dados de tokens.")
            return

        if not dados:
            self._sv_tokens.set("Nenhuma análise registrada ainda.")
            return

        total_in = sum(r["tok_in"] or 0 for r in dados)
        total_out = sum(r["tok_out"] or 0 for r in dados)
        custo_estimado = (total_in * 15 + total_out * 75) / 1_000_000

        linhas = [
            f"{'DIA':<12}  {'ANÁLISES':>8}  {'TOK ENTRADA':>12}  {'TOK SAÍDA':>10}",
            "─" * 50,
        ]
        for r in dados[-15:]:
            linhas.append(
                f"{r['dia']:<12}  {r['analises']:>8}  {r['tok_in'] or 0:>12,}  {r['tok_out'] or 0:>10,}"
            )
        linhas += [
            "─" * 50,
            f"{'TOTAL':<12}  {'':>8}  {total_in:>12,}  {total_out:>10,}",
            "",
            f"Custo estimado (30d): US$ {custo_estimado:.4f}",
            f"  (entrada: ${total_in*15/1_000_000:.4f}  |  saída: ${total_out*75/1_000_000:.4f})",
        ]
        self._sv_tokens.set("\n".join(linhas))

    # ── Aba 5: Tendências ──────────────────────────────────────────────────────

    def _montar_aba_tendencias(self, pai):
        f = tk.Frame(pai, bg=BG, padx=28, pady=24)
        f.pack(fill="both", expand=True)
        tk.Label(f, text="TENDÊNCIAS DE ALERTAS — ÚLTIMOS 7 DIAS",
                 font=("Segoe UI", 11, "bold"), bg=BG, fg=AMARELO).pack(anchor="w", pady=(0, 12))
        self._sv_tendencias = tk.StringVar(value="Carregando...")
        tk.Label(f, textvariable=self._sv_tendencias, font=("Consolas", 9),
                 bg=BG, fg=BRANCO, justify="left").pack(anchor="w")

    # ── Lógica ────────────────────────────────────────────────────────────────

    def _exportar_excel(self):
        from tkinter import filedialog, messagebox

        def _gerar():
            try:
                import report_generator
                destino = filedialog.asksaveasfilename(
                    defaultextension=".xlsx",
                    filetypes=[("Excel", "*.xlsx")],
                    title="Salvar relatório Excel",
                )
                if not destino:
                    return
                caminho = report_generator.gerar_excel_do_db(
                    data_inicio=self._filtro_data_inicio.get().strip() or None,
                    data_fim=self._filtro_data_fim.get().strip() or None,
                    camera_id=self._filtro_camera.get() if self._filtro_camera.get() != "todas" else None,
                    destino=destino,
                )
                self._root.after(0, lambda: messagebox.showinfo(
                    "Exportação concluída", f"Relatório salvo em:\n{caminho}"))
            except Exception as exc:
                self._root.after(0, lambda: messagebox.showerror("Erro", str(exc)))

        threading.Thread(target=_gerar, daemon=True).start()

    def _carregar_dados(self):
        analises = db.buscar_analises_filtradas(
            nivel_risco=self._filtro_nivel.get(),
            camera_id=self._filtro_camera.get(),
            data_inicio=self._filtro_data_inicio.get().strip() or None,
            data_fim=self._filtro_data_fim.get().strip() or None,
            limite=300,
        )

        cameras = ["todas"] + db.buscar_cameras_distintas()
        self._cb_camera["values"] = cameras

        for item in self._tree.get_children():
            self._tree.delete(item)

        fb_map = self._mapa_feedbacks()

        for a in analises:
            hora = a["timestamp_analise"][:19].replace("T", " ")
            conf = f"{a['confianca']*100:.0f}%"
            nivel = a["nivel_risco"]
            fb = fb_map.get(a["id"], "—")
            self._tree.insert("", "end",
                              values=(hora, a["camera_id"], nivel.upper(), conf, fb),
                              iid=str(a["id"]),
                              tags=(nivel,))

        self._atualizar_estatisticas()
        self._atualizar_perguntas()
        self._atualizar_aba_tokens()
        self._atualizar_tendencias()

    def _mapa_feedbacks(self) -> dict:
        conn = db.get_connection()
        rows = conn.execute(
            "SELECT analise_id, rotulo FROM feedbacks ORDER BY created_at ASC"
        ).fetchall()
        result = {}
        for r in rows:
            result[r["analise_id"]] = "Correto" if r["rotulo"] == "correto" else "Falso Pos."
        return result

    def _on_selecionar(self, _event):
        sel = self._tree.selection()
        if not sel:
            return
        analise_id = int(sel[0])
        conn = db.get_connection()
        row = conn.execute("SELECT * FROM analises WHERE id=?", (analise_id,)).fetchone()
        if not row:
            return

        self._analise_selecionada = dict(row)
        comps = json.loads(row["comportamentos"]) if row["comportamentos"] else []
        texto = (
            f"Camera:    {row['camera_id']}\n"
            f"Horario:   {row['timestamp_analise'][:19]}\n"
            f"Nivel:     {row['nivel_risco'].upper()}\n"
            f"Confianca: {row['confianca']*100:.0f}%\n"
            f"Tokens:    {row['tokens_entrada'] or 0}/{row['tokens_saida'] or 0}\n\n"
            f"Comportamentos:\n" +
            "\n".join(f"  - {c}" for c in comps) +
            f"\n\nAcao:\n  {row['acao_recomendada'] or '---'}"
        )
        self._sv_detalhe.set(texto)
        self._sv_fb_status.set("")
        self._text_obs.delete("1.0", "end")

        # Mostrar botão de clipe somente quando o arquivo existe em disco
        clip = (self._analise_selecionada.get("clip_path") or "").strip()
        if clip and Path(clip).exists():
            self._btn_clip.pack(fill="x", pady=(0, 4))
        else:
            self._btn_clip.pack_forget()

    def _abrir_player(self):
        if not self._analise_selecionada:
            return

        def _ao_salvar(dest: str):
            self._text_obs.insert("end", f"\n[Clipe salvo em: {dest}]")
            self._sv_fb_status.set("Clipe salvo localmente.")
            self._analise_selecionada["_clip_salvo"] = True

        def _ao_descartar():
            analise_id = self._analise_selecionada["id"]
            threading.Thread(
                target=lambda: db.deletar_clip_analise(analise_id), daemon=True
            ).start()
            self._btn_clip.pack_forget()
            self._analise_selecionada["clip_path"] = None
            self._sv_fb_status.set("Clipe descartado.")

        VideoPlayerDialog(
            self._root, self._analise_selecionada,
            on_salvar=_ao_salvar, on_descartar=_ao_descartar,
        )

    def _abrir_chat(self):
        if not self._analise_selecionada:
            self._sv_fb_status.set("Selecione uma deteccao primeiro.")
            return

        def _ao_aprender(dados: dict):
            rotulo = dados.get("rotulo", "falso_positivo")
            obs    = dados.get("observacao", "")
            ajuste = dados.get("ajuste_sugerido", "manter")

            # Preenche observação com o resumo extraído
            self._text_obs.delete("1.0", "end")
            if obs:
                self._text_obs.insert("1.0", obs)

            # Salva feedback com rótulo extraído da conversa
            self._salvar_feedback(rotulo)

            # Ajuste imediato de sensibilidade (sem esperar calibração estatística)
            if ajuste != "manter":
                try:
                    import mosaic
                    mosaic.ajuste_direto_todos(ajuste)
                except Exception:
                    pass

        ChatDialog(self._root, self._analise_selecionada, on_aprendizado=_ao_aprender)

    def _salvar_feedback(self, rotulo: str):
        if not self._analise_selecionada:
            self._sv_fb_status.set("Selecione uma deteccao primeiro.")
            return
        analise_id = self._analise_selecionada["id"]
        obs = self._text_obs.get("1.0", "end-1c").strip()

        def _gravar():
            db.salvar_feedback(analise_id, rotulo, obs)
            try:
                import mosaic
                mosaic.recalibrar_todos()
            except Exception:
                pass

        threading.Thread(target=_gravar, daemon=True).start()

        # Deleta clip automaticamente ao dar feedback (a menos que tenha sido salvo)
        clip = (self._analise_selecionada.get("clip_path") or "").strip()
        if clip and Path(clip).exists() and not self._analise_selecionada.get("_clip_salvo"):
            threading.Thread(
                target=lambda: db.deletar_clip_analise(analise_id), daemon=True
            ).start()
            self._btn_clip.pack_forget()
            self._analise_selecionada["clip_path"] = None

        status = "Salvo: CORRETO" if rotulo == "correto" else "Salvo: FALSO POSITIVO"
        self._sv_fb_status.set(status)
        self._text_obs.delete("1.0", "end")
        self._root.after(600, self._carregar_dados)

    def _atualizar_estatisticas(self):
        stats = db.estatisticas()
        taxa = stats.get("taxa_falsos_positivos")
        taxa_str = f"{taxa*100:.1f}%" if taxa is not None else "sem dados"

        self._sv_resumo.set(
            f"Total: {stats['total_analises']}  |  "
            f"Alertas: {stats['total_alertas']}  |  "
            f"Falsos Pos.: {stats['falsos_positivos']} ({taxa_str})"
        )

        linhas_stats = [
            f"Total de analises:         {stats['total_analises']}",
            f"Total de alertas:          {stats['total_alertas']}",
            f"Feedbacks dados:           {stats['com_feedback']}",
            f"  - Corretos:              {stats['corretos']}",
            f"  - Falsos positivos:      {stats['falsos_positivos']}",
            f"Taxa de falsos positivos:  {taxa_str}",
            f"Perguntas pendentes:       {stats['perguntas_pendentes']}",
            f"Exemplos few-shot ativos:  {stats['exemplos_fewshot']}",
            "",
            "CALIBRAÇÃO POR CÂMERA  (mín. 30 feedbacks para calibrar automaticamente):",
        ]

        try:
            import calibrator
            cameras = db.buscar_cameras_distintas()
            conn = db.get_connection()
            if cameras:
                for cam in cameras:
                    r = calibrator.resumo_calibracao(conn, cam)
                    fb    = r["com_feedback"]
                    falta = max(0, 30 - fb)
                    barra = "█" * min(fb, 30) + "░" * falta
                    status = "✔ calibrada" if r["pronto_para_calibrar"] else f"faltam {falta}"
                    linhas_stats.append(
                        f"  {cam:<18} [{barra}] {fb:>2}/30  {status}"
                    )
            else:
                linhas_stats.append("  Nenhuma câmera registrada ainda.")
        except Exception:
            linhas_stats.append("  (calibrador indisponível)")

        self._sv_stats_full.set("\n".join(linhas_stats))

    def _atualizar_perguntas(self):
        perguntas = db.buscar_perguntas_pendentes()
        n = len(perguntas)

        if n > 0:
            self._sv_badge.set(f"  {n} pergunta(s) pendente(s)  ")
            self._lbl_badge.pack(side="right", padx=(0, 8))
        else:
            self._sv_badge.set("")
            self._lbl_badge.pack_forget()

        self._nb.tab(1, text=f"  Perguntas ({n})  ")

        for w in self._frame_perguntas.winfo_children():
            w.destroy()

        if not perguntas:
            tk.Label(self._frame_perguntas, text="Nenhuma pergunta pendente.",
                     font=FONT_LABEL, bg=BG, fg=CINZA,
                     padx=24, pady=24).pack()
            return

        for p in perguntas:
            self._montar_card_pergunta(p)

    def _montar_card_pergunta(self, p: dict):
        card = tk.Frame(self._frame_perguntas, bg=BG_CARD, padx=18, pady=14)
        card.pack(fill="x", padx=12, pady=6)

        nivel = p.get("nivel_risco", "atencao")
        cor = NIVEL_COR.get(nivel, CINZA)
        conf = p.get("confianca", 0)
        cabecalho = (
            f"{p.get('camera_id','?')}  |  "
            f"{str(p.get('timestamp_analise',''))[:19]}  |  "
            f"{nivel.upper()}  |  Conf: {conf*100:.0f}%"
        )
        tk.Label(card, text=cabecalho, font=FONT_MONO,
                 bg=BG_CARD, fg=cor).pack(anchor="w")

        tk.Label(card, text=p["pergunta"], font=FONT_LABEL,
                 bg=BG_CARD, fg=BRANCO, wraplength=700,
                 justify="left", pady=8).pack(anchor="w")

        # Opções rápidas
        opcoes = json.loads(p["opcoes"]) if p.get("opcoes") else []
        if opcoes:
            tk.Label(card, text="Resposta rápida:", font=FONT_SMALL,
                     bg=BG_CARD, fg=CINZA).pack(anchor="w", pady=(0, 4))
            brow = tk.Frame(card, bg=BG_CARD)
            brow.pack(fill="x")
            for op in opcoes:
                _btn(brow, op,
                     lambda pid=p["id"], r=op: self._responder_pergunta(pid, r),
                     bg=CINZA_ESC, fg=BRANCO).pack(side="left", padx=(0, 6), pady=(0, 6))

        # Separador
        tk.Frame(card, bg=CINZA_ESC, height=1).pack(fill="x", pady=(8, 8))

        # Explicação livre
        tk.Label(card,
                 text="Ou explique com suas palavras o que acontecia na cena:",
                 font=FONT_SMALL, bg=BG_CARD, fg=CINZA).pack(anchor="w", pady=(0, 4))

        frm_txt = tk.Frame(card, bg=BG_CARD)
        frm_txt.pack(fill="x")
        txt = tk.Text(
            frm_txt, font=("Segoe UI", 9), bg="#0C1825", fg=BRANCO,
            insertbackground=AMARELO, height=3, wrap="word", relief="flat",
            highlightthickness=1, highlightbackground=CINZA_ESC,
        )
        sb_txt = ttk.Scrollbar(frm_txt, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb_txt.set)
        sb_txt.pack(side="right", fill="y")
        txt.pack(fill="x")
        txt.insert("1.0", "Ex: o operador estava ajustando o equipamento, não havia risco...")

        txt.bind("<FocusIn>", lambda e, t=txt: t.delete("1.0", "end")
                 if t.get("1.0", "end-1c").startswith("Ex:") else None)

        brow2 = tk.Frame(card, bg=BG_CARD)
        brow2.pack(anchor="w", pady=(6, 0))
        _btn(brow2, "  Enviar Explicação  ",
             lambda pid=p["id"], t=txt: self._responder_pergunta_livre(pid, t),
             bg=AZUL, fg=BRANCO).pack(side="left")

    def _atualizar_tendencias(self):
        try:
            t = db.tendencias(dias=7)
        except Exception:
            self._sv_tendencias.set("Erro ao carregar tendências.")
            return

        linhas = [f"Período: últimos {t['dias']} dias\n"]

        linhas.append("ALERTAS POR NÍVEL:")
        if t["por_nivel"]:
            for r in t["por_nivel"]:
                bar = "█" * min(r["total"], 40)
                linhas.append(f"  {r['nivel_risco'].upper():<10} {r['total']:>5}  {bar}")
        else:
            linhas.append("  Nenhum alerta no período.")

        linhas.append("\nALERTAS POR CÂMERA:")
        if t["por_camera"]:
            for r in t["por_camera"]:
                bar = "█" * min(r["alertas"], 40)
                linhas.append(f"  {r['camera_id']:<16} {r['alertas']:>5}  {bar}")
        else:
            linhas.append("  Nenhum alerta no período.")

        self._sv_tendencias.set("\n".join(linhas))

    def _responder_pergunta(self, pergunta_id: int, resposta: str):
        threading.Thread(
            target=lambda: db.responder_pergunta(pergunta_id, resposta),
            daemon=True
        ).start()
        self._root.after(500, self._carregar_dados)

    def _responder_pergunta_livre(self, pergunta_id: int, txt_widget: tk.Text):
        texto = txt_widget.get("1.0", "end-1c").strip()
        if not texto or texto.startswith("Ex:"):
            return
        self._responder_pergunta(pergunta_id, texto)


# ── Ponto de entrada ───────────────────────────────────────────────────────────

def abrir_training():
    root = tk.Tk()
    TrainingTab(root)
    root.wait_window(root)
    import gc as _gc; _gc.collect()


if __name__ == "__main__":
    abrir_training()
