import datetime
import re
import sqlite3
import time
from pathlib import Path

import h5py
import numpy as np
from lib.pparser import emRadParser


def safe_slug(value):
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return slug or "recording"


class RecordingStore:
    """SQLite-backed storage for one radar recording session."""

    FS = round(8e6 / 1024 / 8)
    SAMPLES_PER_PACKET = 32
    PAYLOAD_COLUMNS = 10
    MISSING_FILL_VALUE = -1
    SEQUENCE_MODULO = 2**32
    CHANNEL_VALID_STD_THRESHOLD = 1.0

    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA synchronous = NORMAL")
        self.connection.execute("PRAGMA temp_store = MEMORY")
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self.parser = emRadParser()
        self._setup_schema()

    @staticmethod
    def default_recordings_root():
        documents = Path.home() / "Documents"
        if documents.exists():
            return documents / "EmpkinS Radar Recordings"
        return Path.cwd() / "recordings"

    @classmethod
    def create_new(cls, recordings_root=None, recording_id=None):
        started = datetime.datetime.now()
        if recording_id is None:
            recording_id = started.strftime("%Y-%m-%d_%H-%M-%S")

        root = Path(recordings_root) if recordings_root else cls.default_recordings_root()
        recording_dir = root / safe_slug(recording_id)
        if recording_dir.exists():
            base_dir = recording_dir
            suffix = 2
            while recording_dir.exists():
                recording_dir = Path(f"{base_dir}-{suffix}")
                suffix += 1
        recording_dir.mkdir(parents=True, exist_ok=False)
        db_path = recording_dir / "recording.sqlite"

        store = cls(db_path)
        store.start_session(recording_id)
        return store

    def _setup_schema(self):
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recording_id TEXT NOT NULL,
                started_at REAL NOT NULL,
                stopped_at REAL,
                db_path TEXT NOT NULL,
                notes TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS packets (
                timestamp REAL NOT NULL,
                sensor_id INTEGER,
                sequence_id INTEGER,
                data_format INTEGER,
                uptime INTEGER,
                dummy1 INTEGER,
                dummy2 INTEGER,
                data_size INTEGER,
                data BLOB
            );

            CREATE TABLE IF NOT EXISTS measurements (
                measurement_id char(128) NOT NULL,
                comments char(128) NOT NULL,
                sensor_id INTEGER,
                meas_start INTEGER,
                meas_stop INTEGER,
                processed BOOL
            );

            CREATE TABLE IF NOT EXISTS export_ranges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                start_time REAL NOT NULL,
                stop_time REAL NOT NULL,
                output_path TEXT,
                created_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_packets_time ON packets(timestamp);
            CREATE INDEX IF NOT EXISTS idx_packets_sensor_time
                ON packets(sensor_id, timestamp);
            """
        )
        self.connection.commit()

    def start_session(self, recording_id):
        self.connection.execute(
            """
            INSERT INTO sessions(recording_id, started_at, db_path)
            VALUES (?, ?, ?)
            """,
            (recording_id, time.time(), str(self.db_path)),
        )
        self.connection.commit()

    def stop_open_session(self):
        self.connection.execute(
            """
            UPDATE sessions
            SET stopped_at = ?
            WHERE stopped_at IS NULL
            """,
            (time.time(),),
        )
        self.connection.commit()

    def insert_packet(self, packet):
        self.connection.execute(
            "INSERT INTO packets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                packet["timestamp"],
                packet["sensor_id"],
                packet["sequence_id"],
                packet["data_format"],
                packet["uptime"],
                packet["dummy1"],
                packet["dummy2"],
                packet["data_size"],
                packet["data"],
            ),
        )

    def insert_packets(self, packets):
        self.connection.executemany(
            "INSERT INTO packets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    packet["timestamp"],
                    packet["sensor_id"],
                    packet["sequence_id"],
                    packet["data_format"],
                    packet["uptime"],
                    packet["dummy1"],
                    packet["dummy2"],
                    packet["data_size"],
                    packet["data"],
                )
                for packet in packets
            ],
        )
        self.connection.commit()

    def get_time_bounds(self):
        row = self.connection.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM packets"
        ).fetchone()
        if not row or row[0] is None or row[1] is None:
            return None
        return row[0], row[1]

    def get_coverage(self, bucket_seconds=60):
        rows = self.connection.execute(
            """
            SELECT CAST(timestamp / ? AS INTEGER) AS bucket, COUNT(*)
            FROM packets
            GROUP BY bucket
            ORDER BY bucket
            """,
            (bucket_seconds,),
        ).fetchall()
        return [
            (bucket * bucket_seconds, (bucket + 1) * bucket_seconds, count)
            for bucket, count in rows
        ]

    def get_recent_packets(self, sensor_id, seconds=5, limit=200):
        now = time.time()
        rows = self.connection.execute(
            """
            SELECT timestamp, sensor_id, sequence_id, data_format, uptime,
                   dummy1, dummy2, data_size, data
            FROM packets
            WHERE sensor_id = ? AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (sensor_id, now - seconds, now, limit),
        ).fetchall()
        return rows[::-1]

    def _missing_sequences_between(self, previous_sequence, current_sequence):
        if previous_sequence is None:
            return []

        gap = current_sequence - previous_sequence - 1
        if gap >= 0:
            return list(range(previous_sequence + 1, current_sequence))

        wrap_gap = self.SEQUENCE_MODULO - previous_sequence - 1 + current_sequence
        if wrap_gap <= 0 or wrap_gap > 100000:
            return []

        return list(range(previous_sequence + 1, self.SEQUENCE_MODULO)) + list(
            range(0, current_sequence)
        )

    def _channel_is_valid(self, packet_data, channel_index):
        if packet_data.shape[1] < 8:
            return False
        i_col = channel_index * 2
        q_col = i_col + 1
        return float(np.std(packet_data[:, [i_col, q_col]])) > self.CHANNEL_VALID_STD_THRESHOLD

    def export_range_to_h5(self, start_time, stop_time, output_path, node_id=0):
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sensor_id = int(node_id)

        with h5py.File(output_path, "w") as h5:
            group = h5.create_group("Radar")
            group.attrs["start"] = float(start_time)
            group.attrs["stop"] = float(stop_time)
            group.attrs["node_id"] = int(node_id)
            group.attrs["created_at"] = time.time()
            group.attrs["sample_rate_hz"] = self.FS
            group.attrs["missing_fill_value"] = self.MISSING_FILL_VALUE
            group.attrs["channel_valid_std_threshold"] = self.CHANNEL_VALID_STD_THRESHOLD

            rows = self.connection.execute(
                """
                SELECT timestamp, sequence_id, data
                FROM packets
                WHERE sensor_id = ? AND timestamp BETWEEN ? AND ?
                ORDER BY timestamp, sequence_id
                """,
                (sensor_id, start_time, stop_time),
            ).fetchall()

            parsed_packets = []
            packet_times = []
            packet_sequences = []
            missing_sequences = []
            invalid_channel_sequences = {index: [] for index in range(4)}
            previous_sequence = None
            missing_packet = np.full(
                (self.SAMPLES_PER_PACKET, self.PAYLOAD_COLUMNS),
                self.MISSING_FILL_VALUE,
                dtype=np.int32,
            )

            for timestamp, sequence_id, payload in rows:
                for missing_sequence in self._missing_sequences_between(
                    previous_sequence, sequence_id
                ):
                    parsed_packets.append(missing_packet)
                    packet_times.append(np.nan)
                    packet_sequences.append(missing_sequence)
                    missing_sequences.append(missing_sequence)

                parsed = self.parser.parse(payload)
                if parsed is not None:
                    parsed = parsed.copy()
                    for channel_index in range(4):
                        if not self._channel_is_valid(parsed, channel_index):
                            i_col = channel_index * 2
                            q_col = i_col + 1
                            parsed[:, [i_col, q_col]] = self.MISSING_FILL_VALUE
                            invalid_channel_sequences[channel_index].append(sequence_id)
                    parsed_packets.append(parsed)
                    packet_times.append(timestamp)
                    packet_sequences.append(sequence_id)
                    previous_sequence = sequence_id

            if parsed_packets:
                data = np.concatenate(parsed_packets)
            else:
                data = np.empty((0, self.PAYLOAD_COLUMNS), dtype=np.int32)

            channel_columns = {
                "rad1": [0, 1, 8, 9],
                "rad2": [2, 3, 8, 9],
                "rad3": [4, 5, 8, 9],
                "rad4": [6, 7, 8, 9],
            }
            for name, columns in channel_columns.items():
                group.create_dataset(name, data=data[:, columns])

            group.create_dataset(
                "packet_timestamps",
                data=np.asarray(packet_times, dtype=float),
            )
            group.create_dataset(
                "packet_sequence_ids",
                data=np.asarray(packet_sequences, dtype=np.uint32),
            )
            group.create_dataset(
                "missing_packet_sequence_ids",
                data=np.asarray(missing_sequences, dtype=np.uint32),
            )
            group.attrs["missing_packet_count"] = len(missing_sequences)
            for channel_index in range(4):
                name = f"rad{channel_index + 1}"
                invalid_sequences = invalid_channel_sequences[channel_index]
                group.create_dataset(
                    f"{name}_invalid_channel_sequence_ids",
                    data=np.asarray(invalid_sequences, dtype=np.uint32),
                )
                group.attrs[f"{name}_invalid_channel_packet_count"] = len(invalid_sequences)

        self.connection.execute(
            """
            INSERT INTO export_ranges(label, start_time, stop_time, output_path, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                output_path.stem,
                float(start_time),
                float(stop_time),
                str(output_path),
                time.time(),
            ),
        )
        self.connection.commit()
        return output_path

    def close(self):
        self.connection.commit()
        self.connection.close()
