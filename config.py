import os
import logging
from typing import Any, Dict, Optional
import toml
import inifile
import yaml
import shutil
import requests

class Config:
    """
    Config class to load and save config file with validation and recovery features.

    check_level: A string of four digits (default: "1111")
    - First digit: Error level
        0 - No validation
        1 - Validate but ignore errors and only log warnings
        2 - Validate and raise errors on failure
    - Second digit: Type check
        0 - No type check
        1 - Allow incorrect types with warnings
        2 - Enforce correct types
    - Third digit: Field check
        0 - No restrictions
        1 - Allow extra fields but require all standard fields
        2 - Strict match of fields (no extra or missing fields)
        3 - Allow missing fields but no extra fields
    - Fourth digit: Config recovery
        0 - No recovery
        1 - Fix config file by removing extra fields and filling missing / type error fields
        2 - Automatically recover to default config and create backups (rename original files sequentially)
    """
    path: str
    type: str
    check_level: str = "1111"
    recover_path: Optional[str] = None
    config: Dict[str, Any]
    logger: logging.Logger

    def __init__(self, path: str, type: Optional[str] = None,
                 recover_path: Optional[str] = None, check_level: str = "1111"
                 ) -> None:
        """
        Load config file from path
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.path = path
        if path.endswith(".ini"):
            type = "ini"
        elif path.endswith(".toml"):
            type = "toml"
        elif path.endswith(".yaml") or path.endswith(".yml"):
            type = "yaml"
        else:
            if check_level[0] == "2":
                self.logger.error("Unsupported config file type.")
                raise ValueError("Unsupported config file type.")
            self.logger.warning("Unsupported config file type.")
        self.config = {}
        self.load_config()
        if type is not None:
            if self.validate_config() == False:
                if check_level[0] == "2":
                    self.logger.error("Config file validation failed.")
                    raise ValueError("Config file validation failed.")
                elif check_level[0] == "1":
                    self.logger.warning("Config file validation failed.")
        self.save_config()

    def __getitem__(self, key: str) -> Any:
        """
        Allow dictionary-style access to the config
        """
        return self.config[key]

    def __setitem__(self, key: str, value: Any) -> None:
        """
        Allow dictionary-style setting of the config
        """
        self.config[key] = value

    def load_config(self) -> None:
        """
        Load config file from path
        """
        if not os.path.exists(self.path):
            self.logger.warning(f"Config file {self.path} not found")
            self.config = {}
        else:
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    if self.path.endswith(".toml"):
                        self.config = toml.load(f)
                    elif self.path.endswith(".ini"):
                        parser = inifile.IniFile()
                        parser.read_file(f)
                        self.config = {section: dict(parser.items(section)) for section in parser.sections()}
                    elif self.path.endswith(".yaml") or self.path.endswith(".yml"):
                        self.config = yaml.safe_load(f)
                    else:
                        raise ValueError("Unsupported config file type.")
                    self.logger.info(f"Config file loaded from {self.path}")
                    self.logger.debug(f"Config file content: {self.config}")
            except Exception as e:
                self.logger.error(f"Error loading config file: {e}")
                raise ValueError(f"Error loading config file: {e}")

    def validate_config(self) -> bool:
        """
        Validate config file based on check_level.
        """
        if self.check_level[0] == "0":
            self.logger.info("Validation skipped due to check_level.")
            return True

        # Load default config for validation
        default_config = self.load_default_config()
        temp_config = Config(self.path, check_level="0000").config

        # Field check
        field_check_level = int(self.check_level[2])
        if field_check_level > 0:
            for key in default_config:
                if key not in temp_config:
                    if field_check_level == 2:
                        self.logger.error(f"Missing required field: {key}")
                        if self.check_level[0] == "2":
                            raise ValueError(f"Missing required field: {key}")
                    elif field_check_level in [1, 3]:
                        self.logger.warning(f"Missing field: {key}, using default value.")
                        temp_config[key] = default_config[key]
            if field_check_level in [1, 3]:
                for key in list(temp_config.keys()):
                    if key not in default_config:
                        self.logger.warning(f"Extra field found: {key}")
                        if field_check_level == 3:
                            del temp_config[key]

        # Type check
        type_check_level = int(self.check_level[1])
        if type_check_level > 0:
            for key, value in default_config.items():
                if key in temp_config and not isinstance(temp_config[key], type(value)):
                    if type_check_level == 2:
                        self.logger.error(f"Incorrect type for field {key}: expected {type(value)}, got {type(temp_config[key])}")
                        if self.check_level[0] == "2":
                            raise TypeError(f"Incorrect type for field {key}")
                    elif type_check_level == 1:
                        self.logger.warning(f"Incorrect type for field {key}, using default value.")
                        temp_config[key] = value

        # Recovery
        if self.check_level[3] in ["1", "2"]:
            backup_path = f"{self.path}.backup"
            shutil.copy(self.path, backup_path)
            self.logger.info(f"Backup created at {backup_path}")
            if self.check_level[3] == "2":
                self.logger.info("Recovering to default config.")
                self.config = default_config
            else:
                self.logger.info("Recovering config with type fixes and field adjustments.")
                self.config = temp_config
            self.save_config()

        self.config = temp_config
        return True

    def load_default_config(self) -> Dict[str, Any]:
        """
        Load the default configuration for validation.
        Automatically detects if the source is a file URL or a network URL.
        """
        if self.recover_path:
            if self.recover_path.startswith("http://") or self.recover_path.startswith("https://"):
                try:
                    response = requests.get(self.recover_path)
                    response.raise_for_status()
                    self.logger.info(f"Default config loaded from network URL: {self.recover_path}")
                    return yaml.safe_load(response.text)  # Assuming YAML format for network URL
                except Exception as e:
                    self.logger.error(f"Failed to load default config from network URL: {e}")
                    raise ValueError(f"Failed to load default config from network URL: {e}")
            elif os.path.exists(self.recover_path):
                try:
                    with open(self.recover_path, "r", encoding="utf-8") as f:
                        if self.recover_path.endswith(".toml"):
                            self.logger.info(f"Default config loaded from file: {self.recover_path}")
                            return toml.load(f)
                        elif self.recover_path.endswith(".ini"):
                            parser = inifile.IniFile()
                            parser.read_file(f)
                            self.logger.info(f"Default config loaded from file: {self.recover_path}")
                            return {section: dict(parser.items(section)) for section in parser.sections()}
                        elif self.recover_path.endswith(".yaml") or self.recover_path.endswith(".yml"):
                            self.logger.info(f"Default config loaded from file: {self.recover_path}")
                            return yaml.safe_load(f)
                        else:
                            raise ValueError("Unsupported default config file type.")
                except Exception as e:
                    self.logger.error(f"Failed to load default config from file: {e}")
                    raise ValueError(f"Failed to load default config from file: {e}")
            else:
                self.logger.error(f"Default config path does not exist: {self.recover_path}")
                raise ValueError(f"Default config path does not exist: {self.recover_path}")
        else:
            self.logger.warning("No recover_path provided.")
            return {}

    def save_config(self) -> None:
        """
        Save config file to path
        """
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                if self.path.endswith(".toml"):
                    toml.dump(self.config, f)
                elif self.path.endswith(".ini"):
                    parser = inifile.IniFile()
                    for section, values in self.config.items():
                        parser.add_section(section)
                        for key, value in values.items():
                            parser.set(section, key, str(value))
                    parser.write(f)
                elif self.path.endswith(".yaml") or self.path.endswith(".yml"):
                    yaml.safe_dump(self.config, f)
                else:
                    raise ValueError("Unsupported config file type.")
            self.logger.info(f"Config file saved to {self.path}")
        except Exception as e:
            self.logger.error(f"Error saving config file: {e}")
            raise ValueError(f"Error saving config file: {e}")
