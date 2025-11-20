import subprocess
import os
from pathlib import Path

test_dir = Path('/tmp/test_pptx')
output_dir = Path('/tmp/test_output')
output_dir.mkdir(exist_ok=True)

env = os.environ.copy()
env.update({'HOME': '/tmp', 'DISPLAY': '', 'SAL_USE_VCLPLUGIN': 'svp'})

print('📊 TEST LIBREOFFICE - FICHIERS PPTX')
print('=' * 60)
print()

if not test_dir.exists():
    print(f'❌ Répertoire {test_dir} introuvable')
    exit(1)

pptx_files = sorted(test_dir.glob('*.pptx'))

if not pptx_files:
    print('❌ Aucun fichier PPTX trouvé')
    exit(1)

for pptx in pptx_files:
    size_mb = pptx.stat().st_size / (1024 * 1024)
    print(f'🔍 {pptx.name:<30} ({size_mb:>6.1f} MB)')

    cmd = [
        '/usr/bin/soffice', '--headless', '--invisible', '--nodefault',
        '--nolockcheck', '--nologo', '--norestore', '--convert-to', 'pdf',
        '--outdir', str(output_dir), str(pptx)
    ]

    try:
        result = subprocess.run(cmd, env=env, timeout=30, capture_output=True, text=True)
        pdf_name = pptx.stem + '.pdf'
        pdf_path = output_dir / pdf_name

        if result.returncode == 0 and pdf_path.exists():
            pdf_size_mb = pdf_path.stat().st_size / (1024 * 1024)
            print(f'   ✅ SUCCÈS - PDF créé ({pdf_size_mb:.1f} MB)')
        else:
            print(f'   ❌ ÉCHEC (exit code: {result.returncode})')
            if 'Fatal exception' in result.stderr or 'Signal 6' in result.stderr:
                print('      → Signal 6 (SIGABRT) - Crash LibreOffice')
    except subprocess.TimeoutExpired:
        print('   ⏱️  TIMEOUT (>30s)')
    except Exception as e:
        print(f'   ❌ ERREUR: {e}')

    print()

print('Tests terminés')
