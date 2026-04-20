"""Painel de Hardware — SPARTA AGENTE IA (somente admin).

Mostra CPU, RAM, GPU, disco, motor de visão e alertas de capacidade.
Atualiza automaticamente a cada 2 segundos via queue + after().
"""
import logging
import os
import queue as _queue
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

BG      = "#050A12"
BG_CARD = "#06101A"
BG_ROW  = "#08131E"
AMA     = "#00D4FF"
AESC    = "#007A9E"
BCOR    = "#C8E8F8"
CINZA   = "#4A6070"
CESC    = "#152030"
VERDE   = "#00CC77"
VERM    = "#FF2255"
LARANJA = "#FF4499"
AZUL    = "#2277EE"

FONT_T  = ("Segoe UI", 11, "bold")
FONT_L  = ("Segoe UI", 9)
FONT_M  = ("Consolas", 9)
FONT_B  = ("Segoe UI", 9, "bold")
FONT_S  = ("Segoe UI", 8)
FONT_XS = ("Segoe UI", 7)

_DB_PATH  = Path("sparta_analytics.db")
_CLIPS    = Path("clips_alertas")
_INTERVAL = 2000  # ms entre atualizações


def _cor_nivel(pct: float) -> str:
    if pct >= 90:
        return VERM
    if pct >= 70:
        return LARANJA
    return VERDE


def _fmt_bytes(b: int) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {u}"
        b /= 1024
    return f"{b:.1f} PB"


def _coletar_dados() -> dict:
    """Coleta métricas do sistema. Roda em thread separada."""
    dados: dict = {}

    try:
        import psutil

        # ── CPU ──────────────────────────────────────────────────────────────
        dados["cpu_pct"]   = psutil.cpu_percent(interval=0.5)
        dados["cpu_count"] = psutil.cpu_count(logical=True)
        dados["cpu_freq"]  = 0.0
        freq = psutil.cpu_freq()
        if freq:
            dados["cpu_freq"] = freq.current

        # Temperatura CPU (nem sempre disponível no Windows)
        dados["cpu_temp"] = None
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for _, entries in temps.items():
                    if entries:
                        dados["cpu_temp"] = entries[0].current
                        break
        except Exception:
            pass

        # ── RAM ──────────────────────────────────────────────────────────────
        mem = psutil.virtual_memory()
        dados["ram_total"]  = mem.total
        dados["ram_usado"]  = mem.used
        dados["ram_pct"]    = mem.percent
        swap = psutil.swap_memory()
        dados["swap_total"] = swap.total
        dados["swap_usado"] = swap.used
        dados["swap_pct"]   = swap.percent

        # ── Disco ─────────────────────────────────────────────────────────────
        disco = psutil.disk_usage(".")
        dados["disco_total"]  = disco.total
        dados["disco_usado"]  = disco.used
        dados["disco_livre"]  = disco.free
        dados["disco_pct"]    = disco.percent

        # DB e clips
        dados["db_tamanho"]    = _DB_PATH.stat().st_size if _DB_PATH.exists() else 0
        dados["clips_tamanho"] = sum(f.stat().st_size for f in _CLIPS.rglob("*")
                                     if f.is_file()) if _CLIPS.exists() else 0

        # ── Processos Python do sistema ────────────────────────────────────
        pid = os.getpid()
        proc = psutil.Process(pid)
        dados["proc_cpu"]  = proc.cpu_percent(interval=0.1)
        dados["proc_ram"]  = proc.memory_info().rss
        dados["proc_threads"] = proc.num_threads()

    except ImportError:
        dados["erro_psutil"] = True
    except Exception as exc:
        dados["erro_psutil"] = str(exc)

    # ── GPU via torch ────────────────────────────────────────────────────────
    dados["gpu_nome"]    = None
    dados["gpu_vram_total"] = 0
    dados["gpu_vram_usado"] = 0
    dados["gpu_pct"]     = None
    dados["gpu_temp"]    = None
    try:
        import torch
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            dados["gpu_nome"]      = props.name
            dados["gpu_vram_total"] = props.total_memory
            dados["gpu_vram_usado"] = torch.cuda.memory_allocated(0)
            # Temperatura via pynvml (opcional)
            try:
                import pynvml
                pynvml.nvmlInit()
                h = pynvml.nvmlDeviceGetHandleByIndex(0)
                dados["gpu_temp"] = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
                util = pynvml.nvmlDeviceGetUtilizationRates(h)
                dados["gpu_pct"]  = util.gpu
            except Exception:
                pass
    except Exception:
        pass

    # ── VisionEngine ────────────────────────────────────────────────────────
    dados["vision_tier"]    = None
    dados["vision_device"]  = None
    dados["vision_modelo"]  = None
    dados["vision_cameras"] = 0
    dados["vision_max_cam"] = 999
    try:
        from vision_engine import VisionEngine
        eng = VisionEngine._instancia
        if eng:
            dados["vision_tier"]   = eng.tier
            dados["vision_device"] = eng.device
            dados["vision_modelo"] = eng._hw["modelo_yolo"]
            dados["vision_cameras"] = len(eng._trackers)
            dados["vision_max_cam"] = eng.max_cameras
    except Exception:
        pass

    # ── Recursos de IA local ─────────────────────────────────────────────────
    recursos: dict = {}

    try:
        import ultralytics
        tier_desc = "—"
        try:
            from vision_engine import VisionEngine
            eng = VisionEngine._instancia
            if eng:
                tier_desc = f"Tier {eng.tier} — max {eng.max_cameras} câm."
        except Exception:
            pass
        recursos["yolo"] = (True, f"v{ultralytics.__version__}  {tier_desc}")
    except ImportError:
        recursos["yolo"] = (False, "não instalado")

    try:
        import cv2 as _cv
        cuda_n = 0
        try:
            cuda_n = _cv.cuda.getCudaEnabledDeviceCount()
        except Exception:
            pass
        recursos["opencv"] = (True, f"v{_cv.__version__}  CUDA: {cuda_n} dev.")
    except ImportError:
        recursos["opencv"] = (False, "não instalado")

    try:
        import deep_sort_realtime  # noqa: F401
        recursos["deepsort"] = (True, "disponível")
    except ImportError:
        recursos["deepsort"] = (False, "não instalado")

    try:
        import cv2 as _cv
        _cv.createBackgroundSubtractorMOG2()
        recursos["mog2"] = (True, "disponível")
    except Exception:
        recursos["mog2"] = (False, "indisponível")

    try:
        import cv2 as _cv
        _hog = _cv.HOGDescriptor()
        _hog.setSVMDetector(_cv.HOGDescriptor.getDefaultPeopleDetector())
        recursos["hog"] = (True, "detector padrão carregado")
    except Exception as _e:
        recursos["hog"] = (False, str(_e)[:40])

    try:
        import cv2 as _cv
        import numpy as _np
        _a = _np.zeros((64, 64), dtype=_np.uint8)
        _cv.calcOpticalFlowFarneback(_a, _a, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        recursos["optical_flow"] = (True, "disponível")
    except Exception:
        recursos["optical_flow"] = (False, "indisponível")

    _modelo_pt = Path("models/yolo_tapete_ouro.pt")
    if _modelo_pt.exists():
        _sz_mb = _modelo_pt.stat().st_size / 1024 ** 2
        recursos["custom_model"] = (True, f"{_sz_mb:.1f} MB")
    else:
        recursos["custom_model"] = (False, "não encontrado em models/")

    try:
        import torch as _torch
        if _torch.cuda.is_available():
            recursos["cuda"] = (True, _torch.cuda.get_device_name(0))
        else:
            recursos["cuda"] = (False, "torch sem CUDA")
    except ImportError:
        recursos["cuda"] = (False, "torch não instalado")

    dados["recursos_ia"] = recursos

    dados["ts"] = datetime.now().strftime("%H:%M:%S")
    return dados


# Referência global — mantém a janela viva sem wait_window()
_janela: tk.Tk | None = None


def janela_aberta() -> bool:
    """Retorna True se o painel ainda está visível."""
    global _janela
    if _janela is None:
        return False
    try:
        return _janela.winfo_exists()
    except Exception:
        _janela = None
        return False


def atualizar_janela():
    """Chama update() na janela aberta — chamado pelo loop principal do OpenCV."""
    global _janela
    if _janela is None:
        return
    try:
        _janela.update()
    except Exception:
        _janela = None


def abrir_hardware_panel():
    global _janela
    # Se já estiver aberta, traz para frente
    if janela_aberta():
        try:
            _janela.lift()
            _janela.focus_force()
        except Exception:
            pass
        return

    root = tk.Tk()
    _janela = root
    root.title("SPARTA AGENTE IA — Hardware")
    root.configure(bg=BG)
    root.resizable(True, True)
    root.minsize(480, 400)
    root.attributes("-topmost", True)
    # SEM grab_set() — painel não-modal para câmera continuar exibindo

    # ── Cabeçalho ─────────────────────────────────────────────────────────────
    cab = tk.Frame(root, bg=AMA, padx=16, pady=10)
    cab.pack(fill="x")
    tk.Label(cab, text="Monitor de Hardware", font=FONT_T, bg=AMA, fg=BG).pack(side="left")
    sv_ts = tk.StringVar(value="")
    tk.Label(cab, textvariable=sv_ts, font=FONT_S, bg=AMA, fg="#666600").pack(side="right")

    # ── Rodapé fixo ───────────────────────────────────────────────────────────
    frm_rod = tk.Frame(root, bg="#04080F", padx=20, pady=8)
    frm_rod.pack(fill="x", side="bottom")
    tk.Frame(frm_rod, bg=CESC, height=1).pack(fill="x", pady=(0, 6))

    _after_id = [None]

    def _fechar():
        global _janela
        if _after_id[0]:
            try:
                root.after_cancel(_after_id[0])
            except Exception:
                pass
        _janela = None
        root.destroy()
        import gc as _gc; _gc.collect()

    root.protocol("WM_DELETE_WINDOW", _fechar)
    b_fechar = tk.Label(frm_rod, text="   Fechar   ", font=FONT_B,
                        bg=CESC, fg=BCOR, padx=14, pady=7, cursor="hand2")
    b_fechar.bind("<Button-1>", lambda _: _fechar())
    b_fechar.bind("<Enter>",    lambda _: b_fechar.config(bg="#555555"))
    b_fechar.bind("<Leave>",    lambda _: b_fechar.config(bg=CESC))
    b_fechar.pack(side="right")

    sv_auto = tk.StringVar(value="● Atualizando automaticamente (2s)")
    tk.Label(frm_rod, textvariable=sv_auto, font=FONT_XS,
             bg="#04080F", fg="#445544").pack(side="left")

    # ── Corpo com rolagem ─────────────────────────────────────────────────────
    frm_scroll = tk.Frame(root, bg=BG)
    frm_scroll.pack(fill="both", expand=True)

    canvas_scroll = tk.Canvas(frm_scroll, bg=BG, highlightthickness=0)
    scrollbar = tk.Scrollbar(frm_scroll, orient="vertical",
                             command=canvas_scroll.yview)
    canvas_scroll.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    canvas_scroll.pack(side="left", fill="both", expand=True)

    corpo = tk.Frame(canvas_scroll, bg=BG, padx=16, pady=12)
    _corpo_win = canvas_scroll.create_window((0, 0), window=corpo, anchor="nw")

    def _on_corpo_configure(event=None):
        canvas_scroll.configure(scrollregion=canvas_scroll.bbox("all"))
        canvas_scroll.itemconfig(_corpo_win, width=canvas_scroll.winfo_width())

    corpo.bind("<Configure>", _on_corpo_configure)
    canvas_scroll.bind("<Configure>", _on_corpo_configure)

    def _on_mousewheel(event):
        canvas_scroll.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # bind apenas no canvas e no frame — não usar bind_all (captura eventos globalmente)
    canvas_scroll.bind("<MouseWheel>", _on_mousewheel)
    corpo.bind("<MouseWheel>", _on_mousewheel)
    frm_scroll.bind("<MouseWheel>", _on_mousewheel)

    # ── Helpers de layout ─────────────────────────────────────────────────────
    def _secao(pai, titulo: str):
        tk.Label(pai, text=titulo, font=("Segoe UI", 8, "bold"),
                 bg=BG, fg=AMA).pack(anchor="w", pady=(8, 3))

    def _card(pai) -> tk.Frame:
        f = tk.Frame(pai, bg=BG_ROW, padx=12, pady=8)
        f.pack(fill="x", pady=(0, 4))
        return f

    def _linha(card, chave: str, sv: tk.StringVar,
               negrito: bool = False) -> tk.Label:
        fr = tk.Frame(card, bg=BG_ROW)
        fr.pack(fill="x", pady=2)
        tk.Label(fr, text=f"{chave}:", font=FONT_S, bg=BG_ROW,
                 fg="#AAAAAA", width=22, anchor="w").pack(side="left")
        lbl = tk.Label(fr, textvariable=sv,
                       font=FONT_B if negrito else FONT_M,
                       bg=BG_ROW, fg="#FFFFFF", anchor="w")
        lbl.pack(side="left", fill="x", expand=True)
        return lbl  # retorna para permitir mudar fg dinamicamente

    def _barra(pai, sv_pct: tk.DoubleVar, cor_var: list) -> tk.Canvas:
        c = tk.Canvas(pai, bg="#08131E", height=5,
                      highlightthickness=0, relief="flat")
        c.pack(fill="x", pady=(2, 6))
        barra = c.create_rectangle(0, 0, 0, 5, fill=VERDE, outline="")
        cor_var.append(barra)

        def _atualizar(event=None):
            w = c.winfo_width()
            pct = sv_pct.get()
            cor = _cor_nivel(pct)
            c.coords(barra, 0, 0, int(w * pct / 100), 5)
            c.itemconfig(barra, fill=cor)

        c.bind("<Configure>", lambda _: _atualizar())
        sv_pct.trace_add("write", lambda *_: _atualizar())
        return c

    # ────────────────────────────────────────────────────────────────────────
    # CPU
    # ────────────────────────────────────────────────────────────────────────
    _secao(corpo, "PROCESSADOR (CPU)")
    card_cpu = _card(corpo)
    sv_cpu_pct  = tk.StringVar(value="—")
    sv_cpu_info = tk.StringVar(value="—")
    sv_cpu_temp = tk.StringVar(value="—")
    pct_cpu_v   = tk.DoubleVar(value=0)
    _barra_cpu  = []
    lbl_cpu_pct = _linha(card_cpu, "Uso",          sv_cpu_pct, negrito=True)
    _barra(card_cpu, pct_cpu_v, _barra_cpu)
    _linha(card_cpu, "Núcleos / Freq", sv_cpu_info)
    lbl_cpu_temp = _linha(card_cpu, "Temperatura", sv_cpu_temp)

    # ────────────────────────────────────────────────────────────────────────
    # RAM
    # ────────────────────────────────────────────────────────────────────────
    _secao(corpo, "MEMÓRIA RAM")
    card_ram = _card(corpo)
    sv_ram_uso  = tk.StringVar(value="—")
    sv_ram_swap = tk.StringVar(value="—")
    pct_ram_v   = tk.DoubleVar(value=0)
    _barra_ram  = []
    lbl_ram_uso = _linha(card_ram, "RAM",  sv_ram_uso, negrito=True)
    _barra(card_ram, pct_ram_v, _barra_ram)
    _linha(card_ram, "Swap", sv_ram_swap)

    # ────────────────────────────────────────────────────────────────────────
    # GPU
    # ────────────────────────────────────────────────────────────────────────
    _secao(corpo, "PLACA DE VÍDEO (GPU)")
    card_gpu = _card(corpo)
    sv_gpu_nome  = tk.StringVar(value="Detectando...")
    sv_gpu_vram  = tk.StringVar(value="—")
    sv_gpu_uso   = tk.StringVar(value="—")
    sv_gpu_temp  = tk.StringVar(value="—")
    pct_gpu_v    = tk.DoubleVar(value=0)
    _barra_gpu   = []
    lbl_gpu_nome = _linha(card_gpu, "GPU",         sv_gpu_nome, negrito=True)
    lbl_gpu_vram = _linha(card_gpu, "VRAM",        sv_gpu_vram)
    lbl_gpu_uso  = _linha(card_gpu, "Uso GPU",     sv_gpu_uso)
    _barra(card_gpu, pct_gpu_v, _barra_gpu)
    lbl_gpu_temp = _linha(card_gpu, "Temperatura", sv_gpu_temp)

    # ────────────────────────────────────────────────────────────────────────
    # Disco
    # ────────────────────────────────────────────────────────────────────────
    _secao(corpo, "ARMAZENAMENTO")
    card_disco = _card(corpo)
    sv_disco_livre = tk.StringVar(value="—")
    sv_disco_db    = tk.StringVar(value="—")
    sv_disco_clips = tk.StringVar(value="—")
    pct_disco_v    = tk.DoubleVar(value=0)
    _barra_disco   = []
    lbl_disco_livre = _linha(card_disco, "Livre / Total",   sv_disco_livre, negrito=True)
    _barra(card_disco, pct_disco_v, _barra_disco)
    _linha(card_disco, "Banco de dados",  sv_disco_db)
    _linha(card_disco, "Clips de alerta", sv_disco_clips)

    # ────────────────────────────────────────────────────────────────────────
    # Motor de Visão
    # ────────────────────────────────────────────────────────────────────────
    _secao(corpo, "MOTOR DE VISÃO")
    card_vis = _card(corpo)
    sv_vis_motor  = tk.StringVar(value="—")
    sv_vis_device = tk.StringVar(value="—")
    sv_vis_cams   = tk.StringVar(value="—")
    sv_vis_rec    = tk.StringVar(value="—")
    _linha(card_vis, "Motor / Modelo", sv_vis_motor, negrito=True)
    lbl_vis_device = _linha(card_vis, "Dispositivo",    sv_vis_device)
    _linha(card_vis, "Câmeras ativas", sv_vis_cams)
    lbl_vis_rec    = _linha(card_vis, "Recomendação",   sv_vis_rec)

    # ────────────────────────────────────────────────────────────────────────
    # Recursos de IA Local
    # ────────────────────────────────────────────────────────────────────────
    _secao(corpo, "RECURSOS DE APRENDIZADO LOCAL")
    card_ia = _card(corpo)

    _RECURSOS_INFO = [
        ("yolo",         "YOLOv8"),
        ("opencv",       "OpenCV"),
        ("deepsort",     "DeepSORT"),
        ("mog2",         "MOG2 (Background)"),
        ("hog",          "HOG Detector"),
        ("optical_flow", "Optical Flow"),
        ("custom_model", "Modelo Customizado"),
        ("cuda",         "CUDA / GPU"),
    ]

    sv_recursos: dict = {}
    lbl_recursos_dot: dict = {}

    for _chave, _nome in _RECURSOS_INFO:
        _sv_d = tk.StringVar(value="verificando...")
        _fr = tk.Frame(card_ia, bg=BG_ROW)
        _fr.pack(fill="x", pady=2)
        _lbl_dot = tk.Label(_fr, text="●", font=FONT_S, bg=BG_ROW,
                            fg=CINZA, width=2, anchor="w")
        _lbl_dot.pack(side="left")
        tk.Label(_fr, text=f"{_nome:<22}", font=FONT_M,
                 bg=BG_ROW, fg=BCOR).pack(side="left")
        tk.Label(_fr, textvariable=_sv_d, font=FONT_S,
                 bg=BG_ROW, fg=CINZA).pack(side="left")
        sv_recursos[_chave] = _sv_d
        lbl_recursos_dot[_chave] = _lbl_dot

    # ────────────────────────────────────────────────────────────────────────
    # Processo SPARTA
    # ────────────────────────────────────────────────────────────────────────
    _secao(corpo, "PROCESSO SPARTA")
    card_proc = _card(corpo)
    sv_proc_cpu  = tk.StringVar(value="—")
    sv_proc_ram  = tk.StringVar(value="—")
    sv_proc_thr  = tk.StringVar(value="—")
    _linha(card_proc, "CPU do processo", sv_proc_cpu)
    _linha(card_proc, "RAM do processo", sv_proc_ram)
    _linha(card_proc, "Threads",         sv_proc_thr)

    # ── Alertas ───────────────────────────────────────────────────────────────
    _secao(corpo, "ALERTAS DE CAPACIDADE")
    frm_alertas = tk.Frame(corpo, bg=BG_ROW, padx=12, pady=8)
    frm_alertas.pack(fill="x", pady=(0, 4))
    sv_alertas = tk.StringVar(value="✔  Tudo dentro dos limites normais.")
    lbl_alertas = tk.Label(frm_alertas, textvariable=sv_alertas,
                           font=FONT_L, bg=BG_ROW, fg=VERDE,
                           wraplength=440, justify="left")
    lbl_alertas.pack(anchor="w")

    # ── Queue e atualização ───────────────────────────────────────────────────
    _q: _queue.Queue = _queue.Queue()

    def _poll():
        try:
            while True:
                dados = _q.get_nowait()
                _aplicar(dados)
        except _queue.Empty:
            pass
        try:
            _after_id[0] = root.after(_INTERVAL, _coletar_async)
        except Exception:
            pass

    def _coletar_async():
        threading.Thread(target=lambda: _q.put(_coletar_dados()), daemon=True).start()
        try:
            _after_id[0] = root.after(100, _poll)
        except Exception:
            pass

    def _aplicar(d: dict):
        sv_ts.set(f"Atualizado: {d.get('ts', '')}")

        if d.get("erro_psutil"):
            sv_cpu_pct.set("psutil não disponível")
            return

        # CPU
        cpu = d.get("cpu_pct", 0)
        pct_cpu_v.set(cpu)
        sv_cpu_pct.set(f"{cpu:.1f}%  {'⚠' if cpu >= 70 else '●'}")
        lbl_cpu_pct.config(fg=_cor_nivel(cpu))
        freq = d.get("cpu_freq", 0)
        sv_cpu_info.set(f"{d.get('cpu_count', '?')} núcleos  |  {freq:.0f} MHz")
        temp = d.get("cpu_temp")
        sv_cpu_temp.set(f"{temp:.0f} °C" if temp else "Não disponível")
        if temp:
            lbl_cpu_temp.config(fg=VERM if temp >= 85 else LARANJA if temp >= 70 else VERDE)

        # RAM
        ram_pct = d.get("ram_pct", 0)
        pct_ram_v.set(ram_pct)
        sv_ram_uso.set(
            f"{_fmt_bytes(d.get('ram_usado', 0))} / "
            f"{_fmt_bytes(d.get('ram_total', 0))}  ({ram_pct:.1f}%)"
        )
        lbl_ram_uso.config(fg=_cor_nivel(ram_pct))
        swap_pct = d.get("swap_pct", 0)
        sv_ram_swap.set(
            f"{_fmt_bytes(d.get('swap_usado', 0))} / "
            f"{_fmt_bytes(d.get('swap_total', 0))}  ({swap_pct:.1f}%)"
            if d.get("swap_total", 0) > 0 else "Não configurado"
        )

        # GPU
        gpu_nome = d.get("gpu_nome")
        if gpu_nome:
            sv_gpu_nome.set(gpu_nome)
            lbl_gpu_nome.config(fg=AZUL)
            vt = d.get("gpu_vram_total", 0)
            vu = d.get("gpu_vram_usado", 0)
            vpct = (vu / vt * 100) if vt else 0
            pct_gpu_v.set(vpct)
            sv_gpu_vram.set(f"{_fmt_bytes(vu)} / {_fmt_bytes(vt)}  ({vpct:.1f}%)")
            lbl_gpu_vram.config(fg=_cor_nivel(vpct))
            gpct = d.get("gpu_pct")
            sv_gpu_uso.set(f"{gpct}%" if gpct is not None else "Indisponível")
            if gpct is not None:
                lbl_gpu_uso.config(fg=_cor_nivel(gpct))
            gtemp = d.get("gpu_temp")
            sv_gpu_temp.set(f"{gtemp} °C" if gtemp is not None else "Indisponível")
            if gtemp:
                lbl_gpu_temp.config(fg=VERM if gtemp >= 85 else LARANJA if gtemp >= 70 else VERDE)
        else:
            sv_gpu_nome.set("Sem GPU NVIDIA / CUDA não disponível")
            lbl_gpu_nome.config(fg=CINZA)
            sv_gpu_vram.set("—")
            sv_gpu_uso.set("—")
            sv_gpu_temp.set("—")
            pct_gpu_v.set(0)

        # Disco
        disco_pct = d.get("disco_pct", 0)
        pct_disco_v.set(disco_pct)
        sv_disco_livre.set(
            f"{_fmt_bytes(d.get('disco_livre', 0))} livres / "
            f"{_fmt_bytes(d.get('disco_total', 0))}  ({disco_pct:.1f}% usado)"
        )
        lbl_disco_livre.config(fg=_cor_nivel(disco_pct))
        sv_disco_db.set(_fmt_bytes(d.get("db_tamanho", 0)))
        sv_disco_clips.set(_fmt_bytes(d.get("clips_tamanho", 0)))

        # Motor de visão
        tier   = d.get("vision_tier")
        device = d.get("vision_device", "cpu")
        modelo = d.get("vision_modelo", "—")
        n_cams = d.get("vision_cameras", 0)
        max_c  = d.get("vision_max_cam", 999)
        if tier is not None:
            nomes = {0: "YOLOv8n (Nano)", 1: "YOLOv8s (Small)",
                     2: "YOLOv8m (Medium)", 3: "YOLOv8l (Large)"}
            sv_vis_motor.set(f"{nomes.get(tier, modelo)}  — Tier {tier}")
            is_gpu = device == "cuda"
            sv_vis_device.set("GPU (CUDA)" if is_gpu else "CPU (sem GPU)")
            lbl_vis_device.config(fg=AZUL if is_gpu else LARANJA)
            sv_vis_cams.set(f"{n_cams} / {max_c} suportadas neste hardware")
            if tier == 0 and not is_gpu:
                sv_vis_rec.set("Adicione GPU NVIDIA para análise mais precisa e rápida")
                lbl_vis_rec.config(fg=LARANJA)
            elif n_cams >= max_c * 0.8:
                sv_vis_rec.set("Capacidade de GPU próxima do limite — considere upgrade")
                lbl_vis_rec.config(fg=VERM)
            else:
                sv_vis_rec.set("Hardware adequado para a carga atual")
                lbl_vis_rec.config(fg=VERDE)
        else:
            sv_vis_motor.set("Aguardando 1ª análise para inicializar motor...")
            sv_vis_device.set("—")
            sv_vis_cams.set("—")
            sv_vis_rec.set("—")

        # Processo
        sv_proc_cpu.set(f"{d.get('proc_cpu', 0):.1f}%")
        sv_proc_ram.set(_fmt_bytes(d.get("proc_ram", 0)))
        sv_proc_thr.set(str(d.get("proc_threads", "—")))

        # Recursos de IA local
        for _chave in ("yolo", "opencv", "deepsort", "mog2",
                       "hog", "optical_flow", "custom_model", "cuda"):
            _rec = d.get("recursos_ia", {}).get(_chave)
            if _rec is None:
                continue
            _ativo, _desc = _rec
            sv_recursos[_chave].set(_desc)
            lbl_recursos_dot[_chave].config(fg=VERDE if _ativo else VERM)

        # Alertas
        alertas = []
        if d.get("cpu_pct", 0) >= 90:
            alertas.append("⚠  CPU acima de 90% — risco de perda de frames")
        elif d.get("cpu_pct", 0) >= 75:
            alertas.append("⚡  CPU acima de 75% — monitorar")
        if d.get("ram_pct", 0) >= 90:
            alertas.append("⚠  RAM acima de 90% — sistema pode ficar lento")
        if d.get("disco_livre", float("inf")) < 5 * 1024**3:
            alertas.append("⚠  Menos de 5 GB livres em disco")
        elif d.get("disco_livre", float("inf")) < 15 * 1024**3:
            alertas.append("⡐  Menos de 15 GB livres — considere liberar clips antigos")
        clips_gb = d.get("clips_tamanho", 0) / 1024**3
        if clips_gb > 10:
            alertas.append(f"⡐  Clips ocupando {clips_gb:.1f} GB — revise e limpe")
        gpu_nome = d.get("gpu_nome")
        if not gpu_nome:
            alertas.append("ℹ  Sem GPU — adicione placa NVIDIA para análise mais precisa")

        if alertas:
            sv_alertas.set("\n".join(alertas))
            lbl_alertas.config(fg=VERM if any("⚠" in a for a in alertas) else LARANJA)
        else:
            sv_alertas.set("✔  Tudo dentro dos limites normais.")
            lbl_alertas.config(fg=VERDE)

    # ── Inicia coleta ─────────────────────────────────────────────────────────
    _after_id[0] = root.after(200, _coletar_async)

    root.update_idletasks()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    w  = max(root.winfo_reqwidth(), 520)
    h  = min(root.winfo_reqheight(), sh - 80)
    root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
    # Sem wait_window() — o loop do OpenCV chama atualizar_janela() a cada frame
