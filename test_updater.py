#!/usr/bin/env python3
import unittest
import os
import tempfile
import shutil

# Capture original exists before any patches are applied
ORIGINAL_EXISTS = os.path.exists

from unittest.mock import patch, MagicMock

# Import the logic functions from main.py and elevated_helper
import main
import elevated_helper

class TestUpdaterLogic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Set QT_QPA_PLATFORM to minimal to allow headless widget initialization
        os.environ["QT_QPA_PLATFORM"] = "minimal"
        from PyQt6.QtWidgets import QApplication
        import sys
        cls.app = QApplication.instance()
        if cls.app is None:
            cls.app = QApplication(sys.argv)

    def setUp(self):
        # Create a temporary home directory inside the workspace directory
        workspace_dir = os.path.dirname(os.path.abspath(__file__))
        self.test_dir = tempfile.mkdtemp(dir=workspace_dir)
        self.original_home = os.environ.get("HOME")
        os.environ["HOME"] = self.test_dir
        
        # Mock /opt/antigravity-ide target directory
        self.opt_mock_dir = os.path.join(self.test_dir, "opt", "antigravity-ide")
        os.makedirs(self.opt_mock_dir, exist_ok=True)
        
    def tearDown(self):
        shutil.rmtree(self.test_dir)
        if self.original_home:
            os.environ["HOME"] = self.original_home
        else:
            del os.environ["HOME"]

    @patch('main.os.path.exists')
    @patch('main.subprocess.run')
    def test_desktop_file_creation(self, mock_run, mock_exists):
        # Setup: desktop file does not exist, opt binary exists
        mock_exists.side_effect = lambda path: {
            os.path.expanduser("~/.local/share/applications/antigravity-ide.desktop"): False,
            "/opt/antigravity-ide": True,
            "/opt/antigravity-ide/antigravity-ide": True
        }.get(path, ORIGINAL_EXISTS(path))
        
        # Test creation of desktop file
        main.validate_or_create_desktop_file()
        
        desktop_file_path = os.path.expanduser("~/.local/share/applications/antigravity-ide.desktop")
        self.assertTrue(ORIGINAL_EXISTS(desktop_file_path))
        
        # Verify contents of desktop file
        with open(desktop_file_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        self.assertIn("[Desktop Entry]", content)
        self.assertIn("Exec=/opt/antigravity-ide/antigravity-ide --no-sandbox %U", content)
        self.assertIn("Name=Antigravity IDE", content)
        mock_run.assert_called_once()

    @patch('main.os.path.exists')
    @patch('main.subprocess.run')
    def test_desktop_file_validation_and_update(self, mock_run, mock_exists):
        # Setup: existing desktop file without --no-sandbox
        desktop_file_path = os.path.expanduser("~/.local/share/applications/antigravity-ide.desktop")
        
        # Configure mock first so directory creation doesn't fail
        mock_exists.side_effect = lambda path: {
            desktop_file_path: True,
            "/opt/antigravity-ide": True,
            "/opt/antigravity-ide/antigravity-ide": True
        }.get(path, ORIGINAL_EXISTS(path))
        
        os.makedirs(os.path.dirname(desktop_file_path), exist_ok=True)
        
        with open(desktop_file_path, "w", encoding="utf-8") as f:
            f.write("[Desktop Entry]\nName=Antigravity IDE\nExec=/opt/antigravity-ide/antigravity-ide %U\nType=Application\n")
            
        main.validate_or_create_desktop_file()
        
        # Verify it was updated to include --no-sandbox
        with open(desktop_file_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        self.assertIn("Exec=/opt/antigravity-ide/antigravity-ide --no-sandbox %U", content)
        mock_run.assert_called_once()

    @patch('tarfile.is_tarfile')
    @patch('tarfile.open')
    @patch('os.path.isfile')
    def test_tarball_validation_valid(self, mock_isfile, mock_taropen, mock_is_tarfile):
        mock_isfile.return_value = True
        mock_is_tarfile.return_value = True
        
        # Mock tarfile members
        mock_tar = MagicMock()
        mock_tar.getnames.return_value = ["antigravity-ide-linux/antigravity-ide", "antigravity-ide-linux/resources/app.asar"]
        mock_taropen.return_value.__enter__.return_value = mock_tar
        
        # Instantiate App and test validation logic
        app = main.DropZoneApp()
        is_valid, err = app.verify_tarball_local("my-antigravity-update.tar.gz")
        
        self.assertTrue(is_valid)
        self.assertEqual(err, "")

    @patch('tarfile.is_tarfile')
    @patch('os.path.isfile')
    def test_tarball_validation_invalid_extension(self, mock_isfile, mock_is_tarfile):
        app = main.DropZoneApp()
        is_valid, err = app.verify_tarball_local("update.zip")
        
        self.assertFalse(is_valid)
        self.assertIn("File is not a .tar.gz archive.", err)

    @patch('tarfile.is_tarfile')
    @patch('tarfile.open')
    @patch('os.path.isfile')
    def test_tarball_validation_missing_antigravity(self, mock_isfile, mock_taropen, mock_is_tarfile):
        mock_isfile.return_value = True
        mock_is_tarfile.return_value = True
        
        mock_tar = MagicMock()
        mock_tar.getnames.return_value = ["some-other-app/main.py", "some-other-app/readme.txt"]
        mock_taropen.return_value.__enter__.return_value = mock_tar
        
        app = main.DropZoneApp()
        is_valid, err = app.verify_tarball_local("random_archive.tar.gz")
        
        self.assertFalse(is_valid)
        self.assertIn("Archive does not contain 'antigravity' content.", err)

if __name__ == '__main__':
    unittest.main()
