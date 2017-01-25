import pymysql

from contextlib import contextmanager
from proxysql_tools.entities.proxysql import ProxySQLMySQLBackend, \
    ProxySQLMySQLUser, BACKEND_STATUS_OFFLINE_HARD
from pymysql.cursors import DictCursor


class ProxySQLManager(object):
    def __init__(self, host, port, user, password, socket=None):
        """Initializes the ProxySQL manager.

        :param str host: The ProxySQL host to operate against.
        :param int port: The ProxySQL admin port to connect to.
        :param str user: The ProxySQL admin username.
        :param str password: The ProxySQL admin password.
        """
        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password
        self.socket = socket

    def register_mysql_backend(self, hostgroup_id, hostname, port):
        """Register a MySQL backend with ProxySQL.

        :param int hostgroup_id: The ID of the hostgroup that the MySQL backend
        belongs to.
        :param str hostname: The hostname of the MySQL backend.
        :param int port: The port that the MySQL backend listens on.
        :return bool: True on success, False otherwise.
        """
        backend = ProxySQLMySQLBackend()
        backend.hostgroup_id = hostgroup_id
        backend.hostname = hostname
        backend.port = port

        with self.get_connection() as proxy_conn:
            if self.is_mysql_backend_registered(backend, proxy_conn):
                return True

            return self.insert_or_update_mysql_backend(backend, proxy_conn)

    def deregister_mysql_backend(self, hostgroup_id, hostname, port):
        """Deregister a MySQL backend from ProxySQL database.

        :param int hostgroup_id: The ID of the hostgroup that the MySQL backend
        belongs to.
        :param str hostname: The hostname of the MySQL backend.
        :param int port: The port that the MySQL backend listens on.
        :return bool: True on success, False otherwise.
        """
        backend = ProxySQLMySQLBackend()
        backend.hostgroup_id = hostgroup_id
        backend.hostname = hostname
        backend.port = port

        with self.get_connection() as proxy_conn:
            if not self.is_mysql_backend_registered(backend, proxy_conn):
                return True

            ret = self.update_mysql_backend_status(backend.hostgroup_id,
                                                   backend.hostname,
                                                   backend.port,
                                                   BACKEND_STATUS_OFFLINE_HARD)

            return ret

    def update_mysql_backend_status(self, hostgroup_id,
                                    hostname, port, status):
        """Update the status of a MySQL backend.

        :param int hostgroup_id: The ID of the hostgroup
        that the MySQL backend belongs to.
        :param str hostname: The hostname of the MySQL backend.
        :param int port: The port that the MySQL backend listens on.
        :param str status: MySQL backend status
        :return bool: True on success, False otherwise.
        """
        backend = ProxySQLMySQLBackend()
        backend.hostgroup_id = hostgroup_id
        backend.hostname = hostname
        backend.port = port
        backend.status = status

        with self.get_connection() as proxy_conn:
            if not self.is_mysql_backend_registered(backend, proxy_conn):
                msg = 'MySQL backend %s:%s is not registered' \
                      % (backend.hostname, backend.port)
                raise ProxySQLMySQLBackendUnregistered(msg)

            return self.insert_or_update_mysql_backend(backend, proxy_conn)

    def fetch_mysql_backends(self, hostgroup_id=None):
        """Fetch a list of the MySQL backends registered with ProxySQL, either
        in a particular hostgroup or in all hostgroups.

        :param int hostgroup_id: The ID of the hostgroup
        that the MySQL backend belongs to.
        :return list[ProxySQLMySQLBackend]: A list of ProxySQL backends.
        """
        with self.get_connection() as proxy_conn:
            with proxy_conn.cursor() as cursor:
                sql = "SELECT * FROM mysql_servers"
                params = []
                if hostgroup_id is not None:
                    sql += " WHERE hostgroup_id=%s"
                    params.append(hostgroup_id)

                cursor.execute(sql, tuple(params))
                backends_list = [ProxySQLMySQLBackend(row) for row in cursor]

        return backends_list

    def register_mysql_user(self, username, password, default_hostgroup):
        """Register a MySQL user with ProxySQL.

        :param str username: The MySQL username.
        :param str password: The MySQL user's password hash.
        :param int default_hostgroup: The ID of the hostgroup that is the
        default for this user.
        :return bool: True on success, False otherwise.
        """
        user = ProxySQLMySQLUser()
        user.username = username
        user.password = password
        user.default_hostgroup = default_hostgroup

        with self.get_connection() as proxy_conn:
            if self.is_mysql_user_registered(user, proxy_conn):
                return True

            return self.insert_or_update_mysql_user(user, proxy_conn)

    def fetch_mysql_users(self, default_hostgroup_id=None):
        """Fetch a list of MySQL users registered with ProxySQL,
        either with a particular default_hostgroup or all of them.

        :param int default_hostgroup_id: The ID of the hostgroup
        which is the default for the user.
        :return list[ProxySQLMySQLUser]: A list of MySQL users
        registered with ProxySQL.
        """
        with self.get_connection() as proxy_conn:
            with proxy_conn.cursor() as cursor:
                sql = "SELECT * FROM mysql_users"
                params = []
                if default_hostgroup_id is not None:
                    sql += " WHERE default_hostgroup=%s"
                    params.append(default_hostgroup_id)

                cursor.execute(sql, tuple(params))
                users_list = [ProxySQLMySQLUser(row) for row in cursor]

        return users_list

    def set_variables(self):
        raise NotImplementedError()

    @contextmanager
    def get_connection(self):
        db = None
        try:
            if self.socket is not None:
                db = pymysql.connect(
                    unix_socket=self.socket,
                    user=self.user,
                    passwd=self.password,
                    cursorclass=DictCursor
                )
            elif self.port:
                db = pymysql.connect(
                    host=self.host,
                    port=self.port,
                    user=self.user,
                    passwd=self.password,
                    cursorclass=DictCursor
                )
            else:
                db = pymysql.connect(
                    host=self.host,
                    user=self.user,
                    passwd=self.password,
                    cursorclass=DictCursor
                )

            yield db
        finally:
            if db:
                db.close()

    @staticmethod
    def is_mysql_backend_registered(backend, proxy_conn):
        """Check ProxySQL to verify whether a MySQL server is registered
        with it or not.

        :param ProxySQLMySQLBackend backend: The MySQL backend server
        to check for registration.
        :param Connection proxy_conn: A connection to ProxySQL.
        :return bool: True on success, False otherwise.
        """
        with proxy_conn.cursor() as cursor:
            sql = "SELECT COUNT(*) AS cnt from mysql_servers " \
                  "WHERE hostgroup_id=%s AND hostname=%s AND port=%s"
            cursor.execute(sql, (backend.hostgroup_id,
                                 backend.hostname,
                                 backend.port))
            result = cursor.fetchone()

        return int(result['cnt']) > 0

    @staticmethod
    def is_mysql_user_registered(user, proxy_conn):
        """Check ProxySQL to verify whether a MySQL user is registered
        with it or not.

        :param ProxySQLMySQLUser user: The MySQL user to check
        for registration.
        :param Connection proxy_conn: A connection to ProxySQL.
        :return bool: True on success, False otherwise.
        """
        with proxy_conn.cursor() as cursor:
            sql = "SELECT COUNT(*) AS cnt from mysql_users " \
                  "WHERE username=%s AND backend=%s"
            cursor.execute(sql, (user.username, user.backend))
            result = cursor.fetchone()

        return int(result['cnt']) > 0

    @staticmethod
    def insert_or_update_mysql_backend(backend, proxy_conn):
        """Update the MySQL backend registered with ProxySQL.

        :param ProxySQLMySQLBackend backend: The MySQL backend server.
        :param Connection proxy_conn: A connection to ProxySQL.
        :return bool: True on success, False otherwise.
        """
        backend.validate()

        column_expressions = []
        value_expressions = []
        for key, val in backend.to_primitive().iteritems():
            column_expressions.append(str(key))
            value_expressions.append("'%s'" % pymysql.escape_string(str(val)))

        with proxy_conn.cursor() as cursor:
            sql = "REPLACE INTO mysql_servers(%s) VALUES(%s)" \
                  % (', '.join(column_expressions),
                     ', '.join(value_expressions))
            cursor.execute(sql)
            cursor.execute('LOAD MYSQL SERVERS TO RUNTIME')
            cursor.execute('SAVE MYSQL SERVERS TO DISK')

        return True

    @staticmethod
    def insert_or_update_mysql_user(user, proxy_conn):
        """Update the MySQL backend registered with ProxySQL.

        :param ProxySQLMySQLUser user: The MySQL user
        that will connect to ProxySQL.
        :param Connection proxy_conn: A connection to ProxySQL.
        :return bool: True on success, False otherwise.
        """
        user.validate()

        column_expressions = []
        value_expressions = []
        for key, val in user.to_primitive().iteritems():
            column_expressions.append(str(key))
            value_expressions.append("'%s'" % pymysql.escape_string(str(val)))

        with proxy_conn.cursor() as cursor:
            sql = "REPLACE INTO mysql_users(%s) VALUES(%s)" \
                  % (', '.join(column_expressions),
                     ', '.join(value_expressions))
            cursor.execute(sql)
            cursor.execute('LOAD MYSQL USERS TO RUNTIME')
            cursor.execute('SAVE MYSQL USERS TO DISK')

        return True


class ProxySQLMySQLBackendUnregistered(Exception):
    pass