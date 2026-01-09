import argparse
from pathlib import Path

from engine.backup_engine import backup, list_snapshots, restore, verify, load_config


def main():
    ap = argparse.ArgumentParser(description="Portable Incremental Backup Tool")
    sub = ap.add_subparsers(dest="cmd")

    ap_b = sub.add_parser("backup")
    ap_b.add_argument("--config", required=True)

    ap_l = sub.add_parser("list")
    ap_l.add_argument("--repo", required=True)

    ap_r = sub.add_parser("restore")
    ap_r.add_argument("--repo", required=True)
    ap_r.add_argument("--snapshot", required=True)
    ap_r.add_argument("--to", required=True)

    ap_v = sub.add_parser("verify")
    ap_v.add_argument("--repo", required=True)
    ap_v.add_argument("--snapshot", required=True)

    args = ap.parse_args()

    if args.cmd == "backup":
        repo, sources, exclude, use_vss, maxr = load_config(Path(args.config))
        backup(repo, sources, exclude, use_vss, maxr)

    elif args.cmd == "list":
        for s in list_snapshots(Path(args.repo)):
            print(s)

    elif args.cmd == "restore":
        restore(Path(args.repo), args.snapshot, Path(args.to))

    elif args.cmd == "verify":
        verify(Path(args.repo), args.snapshot)

    else:
        ap.print_help()


if __name__ == "__main__":
    main()
