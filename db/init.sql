USE tripsdb;

CREATE TABLE locations (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  name        VARCHAR(255) NOT NULL UNIQUE,
  latitude    DOUBLE       NOT NULL,
  longitude   DOUBLE       NOT NULL,
  timezone    VARCHAR(64)  NOT NULL DEFAULT 'America/New_York',
  created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE trips (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  location_id     INT          NOT NULL,
  title           VARCHAR(255) NOT NULL UNIQUE,
  start_date      DATE         NOT NULL,
  end_date        DATE         NOT NULL,
  notes           TEXT,
  recommendations TEXT,
  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (location_id) REFERENCES locations(id)
) ENGINE=InnoDB;
