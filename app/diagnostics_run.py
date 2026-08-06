from .quality_diagnostics import collect_diagnostics


if __name__ == '__main__':
    report = collect_diagnostics(write_file=True)
    print(f"diagnostics ok={report.get('quality',{}).get('ok')} version={report.get('version')}")
