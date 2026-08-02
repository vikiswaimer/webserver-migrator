"""Работа с Docker и Docker Compose."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ContainerInfo:
    container_id: str
    name: str
    image: str
    status: str
    mounts: list[dict[str, str]]


class DockerService:
    """Инкапсулирует проверки и операции Docker."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def is_available(self) -> bool:
        return shutil.which("docker") is not None

    def daemon_reachable(self) -> bool:
        if not self.is_available():
            return False
        result = self._run(["docker", "info"], check=False)
        return result.returncode == 0

    def list_running_containers(self) -> list[ContainerInfo]:
        if not self.daemon_reachable():
            return []

        result = self._run(
            ["docker", "ps", "--format", "{{.ID}}"],
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []

        containers: list[ContainerInfo] = []
        for container_id in result.stdout.strip().splitlines():
            info = self._inspect_container(container_id.strip())
            if info is not None:
                containers.append(info)
        return containers

    def stop_containers(self, container_ids: list[str]) -> None:
        if not container_ids:
            self._logger.info("Нет контейнеров для остановки")
            return

        self._logger.warning(
            "Остановка контейнеров: %s",
            ", ".join(container_ids),
        )
        result = self._run(["docker", "stop", *container_ids], check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"Не удалось остановить контейнеры: {result.stderr.strip()}"
            )
        self._logger.info("Контейнеры остановлены")

    def find_compose_files(self, search_root: Path) -> list[Path]:
        names = (
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
        )
        found: list[Path] = []
        if not search_root.is_dir():
            return found

        for path in search_root.rglob("*"):
            if path.is_file() and path.name in names:
                # Ограничиваем глубину относительно search_root
                try:
                    depth = len(path.relative_to(search_root).parts)
                except ValueError:
                    continue
                if depth <= 5:
                    found.append(path.resolve())
        return sorted(set(found))

    def _inspect_container(self, container_id: str) -> ContainerInfo | None:
        result = self._run(
            ["docker", "inspect", container_id],
            check=False,
        )
        if result.returncode != 0:
            return None

        try:
            payload = json.loads(result.stdout)[0]
        except (json.JSONDecodeError, IndexError, KeyError) as exc:
            self._logger.debug("inspect parse error for %s: %s", container_id, exc)
            return None

        mounts = []
        for mount in payload.get("Mounts", []):
            mounts.append(
                {
                    "type": str(mount.get("Type", "")),
                    "source": str(Path(mount.get("Source", "")).resolve())
                    if mount.get("Source")
                    else "",
                    "destination": str(mount.get("Destination", "")),
                    "mode": str(mount.get("Mode", "")),
                }
            )

        name = str(payload.get("Name", "")).lstrip("/")
        state = payload.get("State", {})
        status = str(state.get("Status", "unknown"))
        image = str(payload.get("Config", {}).get("Image", ""))

        return ContainerInfo(
            container_id=container_id,
            name=name,
            image=image,
            status=status,
            mounts=mounts,
        )

    def _run(
        self,
        command: list[str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        self._logger.debug("CMD: %s", " ".join(command))
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise RuntimeError(f"Ошибка запуска команды {command}: {exc}") from exc

        if check and result.returncode != 0:
            raise RuntimeError(
                f"Команда завершилась с кодом {result.returncode}: "
                f"{result.stderr.strip()}"
            )
        return result
