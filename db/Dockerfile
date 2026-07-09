FROM mariadb:11.8
COPY init.sql /docker-entrypoint-initdb.d/
COPY bind.cnf /etc/mysql/conf.d/
EXPOSE 3306
