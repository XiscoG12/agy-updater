#!/usr/bin/env python3
import sys
import os
import shutil
import subprocess
import tarfile

def main():
    # Verify running as root
    if os.geteuid() != 0:
        print("Error: This script must be run as root (via pkexec).", file=sys.stderr)
        sys.exit(1)
        
    if len(sys.argv) < 2:
        print("Error: Tarball path argument is missing.", file=sys.stderr)
        sys.exit(2)
        
    tarball_path = sys.argv[1]
    
    # 1. Validation
    if not os.path.isfile(tarball_path):
        print(f"Error: File '{tarball_path}' does not exist.", file=sys.stderr)
        sys.exit(3)
        
    if not tarball_path.endswith('.tar.gz'):
        print("Error: File is not a .tar.gz archive.", file=sys.stderr)
        sys.exit(4)
        
    try:
        # Check if it is a valid tar file
        if not tarfile.is_tarfile(tarball_path):
            print("Error: File is not a valid tar archive.", file=sys.stderr)
            sys.exit(5)
            
        with tarfile.open(tarball_path, "r:gz") as tar:
            members = tar.getmembers()
            if not members:
                print("Error: Tar archive is empty.", file=sys.stderr)
                sys.exit(6)
            
            # Check if any member has "antigravity" in its path,
            # or if the tarball file name contains it.
            has_antigravity = False
            for m in members:
                if 'antigravity' in m.name.lower():
                    has_antigravity = True
                    break
            
            if not has_antigravity and 'antigravity' not in os.path.basename(tarball_path).lower():
                print("Error: Tar archive does not seem to contain Antigravity IDE.", file=sys.stderr)
                sys.exit(7)
    except Exception as e:
        print(f"Error validating tarball: {e}", file=sys.stderr)
        sys.exit(8)
        
    # 2. Clear out /opt/antigravity-ide/*
    target_dir = '/opt/antigravity-ide'
    print(f"Clearing target directory: {target_dir}...")
    try:
        if os.path.exists(target_dir):
            for filename in os.listdir(target_dir):
                file_path = os.path.join(target_dir, filename)
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
        else:
            os.makedirs(target_dir, mode=0o755, exist_ok=True)
    except Exception as e:
        print(f"Error clearing /opt/antigravity-ide: {e}", file=sys.stderr)
        sys.exit(9)
        
    # 3. Extract the tarball with --strip-components=1
    print(f"Extracting {tarball_path} to {target_dir}...")
    try:
        # Using subprocess to call the GNU tar command since it handles symlinks, permissions,
        # and stripping components natively and robustly on Linux.
        cmd = ["tar", "-xzf", tarball_path, "-C", target_dir, "--strip-components=1"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Error extracting tarball: {result.stderr}", file=sys.stderr)
            sys.exit(10)
    except Exception as e:
        print(f"Error running tar command: {e}", file=sys.stderr)
        sys.exit(11)
        
    # 4. Set appropriate permissions on target directory
    print("Setting permissions on extracted files...")
    try:
        for root, dirs, files in os.walk(target_dir):
            for d in dirs:
                os.chmod(os.path.join(root, d), 0o755)
            for f in files:
                file_p = os.path.join(root, f)
                # Keep execute bit if original had it, otherwise make it readable (644)
                st = os.stat(file_p)
                if st.st_mode & 0o100:
                    os.chmod(file_p, 0o755)
                else:
                    os.chmod(file_p, 0o644)
    except Exception as e:
        print(f"Warning: failed to set permissions: {e}", file=sys.stderr)
        
    print("Elevated installation phase finished successfully!")

if __name__ == '__main__':
    main()
