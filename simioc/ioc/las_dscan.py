from __future__ import annotations

import dataclasses
import logging
import pathlib
from typing import Optional, Tuple, Union

import numpy as np

from caproto import ChannelData
from caproto.server import AsyncLibraryLayer, PVGroup, SubGroup, pvproperty
from simioc.db.utils import write_if_differs

from ..db.motor import Motor
from ..db.qmini import QminiSpectrometer
from .utils import SIM_IOC_PATH, main

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class Dataset:
    positions: np.ndarray
    wavelengths: np.ndarray
    intensities: np.ndarray
    # Importing settings would require las_dispersion_scan to be importable
    # settings: Dict[str, Any]

    def find_closest_spectrum(self, position: float) -> Tuple[np.ndarray, np.ndarray]:
        min_pos = np.min(self.positions)
        max_pos = np.max(self.positions)
        step = self.positions[1] - self.positions[0]
        if position < (min_pos - step) or position > (max_pos + step):
            print('out of range', position, min_pos, max_pos)
            return np.zeros_like(self.intensities[0])

        idx = np.argmin(np.abs(self.positions - position))
        return self.intensities[idx]

    @classmethod
    def from_path(cls, path: Union[pathlib.Path, str]) -> Dataset:
        """
        Load a dataset from the provided path.

        Parameters
        ----------
        path : str
            Directory where the old files are to be found, or a direct path
            to a .npz file.

        Returns
        -------
        Acquisition
            The data from the scan.
        """
        loaded = np.load(path, allow_pickle=False)
        return cls(
            positions=loaded["positions"] * 1e3,  # m -> mm
            wavelengths=loaded["wavelengths"],
            intensities=loaded["intensities"],
        )


class LaserDscanIOC(PVGroup):
    """
    A simulation IOC used for the laser dispersion scan GUI.
    """

    dataset: Dataset

    spectrometer = SubGroup(QminiSpectrometer, prefix="{spectrometer}")
    motor = SubGroup(Motor, prefix="{motor}", velocity=100.0, egu="mm")
    sim_enable = pvproperty(
        name="DScan:SimEnable",
        value=True,
        doc="Enable simulation mode",
    )

    def __init__(self, *args, dataset: Optional[Dataset] = None, **kwargs):
        super().__init__(*args, **kwargs)
        if dataset is None:
            dataset = Dataset.from_path(SIM_IOC_PATH / "dscan_sample.npz")

        min_pos = np.min(dataset.positions)
        max_pos = np.max(dataset.positions)
        print(f"Dataset positions: {min_pos} to {max_pos}")
        self.dataset = dataset

    @sim_enable.scan(period=0.2)
    async def sim_enable(self, instance: ChannelData, async_lib: AsyncLibraryLayer):
        if self.sim_enable.value not in (1, "On"):
            return

        spectrum = self.dataset.find_closest_spectrum(
            self.motor.user_readback_position
        )
        await write_if_differs(self.spectrometer.wavelengths, list(self.dataset.wavelengths))
        await write_if_differs(self.spectrometer.spectrum, list(spectrum))


if __name__ == "__main__":
    main(
        cls=LaserDscanIOC,
        default_prefix="IOC:TST:",
        macros={
            "spectrometer": "DScan:Qmini",
            "motor": "DScan:m1",
        },
    )
