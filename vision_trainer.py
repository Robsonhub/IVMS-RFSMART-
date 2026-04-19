"""Loop de aprendizado ativo — exporta dataset YOLO a partir do DB e re-treina o modelo.

Uso:
  python vision_trainer.py export          # exporta dataset (mínimo 200 exemplos)
  python vision_trainer.py treinar         # fine-tune YOLOv8 no dataset exportado
  python vision_trainer.py tudo            # export + treino em sequência

O Claude API age como "professor": cada análise com fonte='opus' e alerta=True,
combinada com feedbacks de validação, gera dados de treino rotulados.
Após treino, models/yolo_tapete_ouro.pt é carregado automaticamente pelo VisionEngine.
"""
import argparse
import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

DATASET_DIR  = Path("dataset_yolo")
MODELOS_DIR  = Path("models")
MODELO_OUT   = MODELOS_DIR / "yolo_tapete_ouro.pt"
MIN_EXEMPLOS = 200


def exportar_dataset_yolo(output_dir: Path = DATASET_DIR,
                           min_exemplos: int = MIN_EXEMPLOS) -> int:
    """
    Lê análises do DB (fonte='opus', alerta=True) + feedbacks de validação
    e exporta imagens + labels no formato YOLO (.txt com bbox normalizada).

    Retorna número de exemplos exportados.
    """
    import db

    analises = db.buscar_analises(apenas_alertas=True, limite=5000)
    opus_analises = [a for a in analises if a.get("fonte", "") in ("opus", "haiku-triagem")]

    if len(opus_analises) < min_exemplos:
        print(f"[TRAINER] Apenas {len(opus_analises)} exemplos disponíveis "
              f"(mínimo: {min_exemplos}). Acumule mais análises antes de treinar.")
        return 0

    imgs_dir    = output_dir / "images" / "train"
    labels_dir  = output_dir / "labels" / "train"
    imgs_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    exportados = 0
    for analise in opus_analises:
        objetos = analise.get("objetos_detectados") or []
        if not objetos:
            continue

        frame_id = analise.get("frame_id", "")
        if not frame_id:
            continue

        # Labels YOLO: class cx cy w h (normalizados 0-1)
        linhas = []
        for obj in objetos:
            bbox = obj.get("bbox_norm")
            if not bbox or len(bbox) != 4:
                continue
            x1, y1, x2, y2 = bbox
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2
            bw = x2 - x1
            bh = y2 - y1
            linhas.append(f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")

        if not linhas:
            continue

        label_path = labels_dir / f"{frame_id}.txt"
        label_path.write_text("\n".join(linhas), encoding="utf-8")
        exportados += 1

    # Gera data.yaml para o YOLOv8
    yaml_path = output_dir / "data.yaml"
    yaml_path.write_text(
        f"path: {output_dir.resolve()}\n"
        "train: images/train\n"
        "val: images/train\n"  # sem val separado para datasets pequenos
        "nc: 1\n"
        "names: ['pessoa']\n",
        encoding="utf-8",
    )

    print(f"[TRAINER] Dataset exportado: {exportados} exemplos em {output_dir}/")
    return exportados


def retreinar_yolo(dataset_dir: Path = DATASET_DIR,
                   modelo_base: str = "yolov8n.pt",
                   epocas: int = 30) -> bool:
    """
    Fine-tune do YOLOv8 no dataset acumulado.
    Salva modelo customizado em models/yolo_tapete_ouro.pt.
    """
    try:
        from ultralytics import YOLO
    except ImportError:
        print("[TRAINER] ultralytics não instalado. Execute: pip install ultralytics")
        return False

    yaml_path = dataset_dir / "data.yaml"
    if not yaml_path.exists():
        print(f"[TRAINER] Dataset não encontrado em {dataset_dir}/. Execute 'export' primeiro.")
        return False

    MODELOS_DIR.mkdir(exist_ok=True)

    print(f"[TRAINER] Iniciando fine-tune: {modelo_base} | {epocas} épocas")
    model = YOLO(modelo_base)
    results = model.train(
        data=str(yaml_path),
        epochs=epocas,
        imgsz=640,
        batch=8,
        name="tapete_ouro",
        project=str(MODELOS_DIR / "runs"),
        exist_ok=True,
        verbose=False,
    )

    # Copia o best.pt para o caminho padrão do VisionEngine
    best = Path(results.save_dir) / "weights" / "best.pt"
    if best.exists():
        import shutil
        shutil.copy2(best, MODELO_OUT)
        print(f"[TRAINER] Modelo salvo em {MODELO_OUT}")
        print("[TRAINER] Reinicie o sistema para aplicar o modelo customizado.")
        return True

    print("[TRAINER] Treino concluído mas best.pt não encontrado.")
    return False


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="SPARTA — Treinador YOLOv8")
    parser.add_argument("acao", choices=["export", "treinar", "tudo"],
                        help="export: gera dataset | treinar: fine-tune | tudo: ambos")
    parser.add_argument("--min", type=int, default=MIN_EXEMPLOS,
                        help=f"Mínimo de exemplos para exportar (padrão: {MIN_EXEMPLOS})")
    parser.add_argument("--epocas", type=int, default=30,
                        help="Épocas de treinamento (padrão: 30)")
    parser.add_argument("--modelo", default="yolov8n.pt",
                        help="Modelo base para fine-tune (padrão: yolov8n.pt)")
    args = parser.parse_args()

    if args.acao in ("export", "tudo"):
        n = exportar_dataset_yolo(min_exemplos=args.min)
        if n == 0 and args.acao == "tudo":
            sys.exit(1)

    if args.acao in ("treinar", "tudo"):
        ok = retreinar_yolo(modelo_base=args.modelo, epocas=args.epocas)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
