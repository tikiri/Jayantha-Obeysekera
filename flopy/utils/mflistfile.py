import os
import sys
import re
from datetime import datetime, timedelta
import numpy as np


class ListBudget(object):
    """ MODFLOW family list file handling

    Parameters:
    ----------
        file_name : (str) the list file name

    Methods:
    ----------
        get_recarrays : returns flux_in,flux_out,vol_in,vol_out numpy.recarrays for all
            entries in the list file budget.  The columns include stress period and time step

        get_dataframes(start_datetime='1-1-1970') : returns flux and volume dateframes.
            Columns of each dataframe are multiindex on (["in","out"],[budget entries])
            If start_datetime is passed as none, the rows are also multiindex on
            (stress period,time step).  Otherwise, a DatetimeIndex is set.
    Note:
    ----
        The ListBudget class should not be instantiated directly.  Access is
        through derived classes: MfListBudget (MODFLOW), SwtListBudget (SEAWAT)
        and SwrListBudget (MODFLOW with the SWR process)

    Example:
    -------
        >>> mf_list = MfListBudget("my_model.list")
        >>> in_flux, out_flux, in_vol, out_vol = mf_list.get_recarrays()
        >>> df_in, df_out = mf_list.get_dataframes(start_datetime="10-21-2015")

    """

    def __init__(self, file_name):
        raise Exception('base class lstbudget does not have a " +\
        "constructor - must call a derived class')


    def get_cumulative(self):
        """
        Get a recarray with the cumulative water budget items in the list file

        Returns
        ----------
        out : recarray
            Numpy recarray with the water budget items in list file. The
            recarray also includes totim, time_step, and stress_period.

        """
        return self.cum

    def get_incremental(self):
        """
        Get a recarray with the incremental water budget items in the list file

        Returns
        ----------
        out : recarray
            Numpy recarray with the water budget items in list file. The
            recarray also includes totim, time_step, and stress_period.

        """
        return self.inc

    def get_budget(self):
        """
        Get the recarrays with the incremental and cumulative water budget items
        in the list file

        Returns
        ----------
        out : recarrays
            Numpy recarrays with the water budget items in list file. The
            recarray also includes totim, time_step, and stress_period. A
            separate recarray is returned for the incremental and cumulative
            water budget entries.

        """
        return self.inc, self.cum

    def get_times(self):
        """
        Get a list of unique water budget times in the list file

        Returns
        ----------
        out : list of floats
            List contains unique water budget simulation times (totim) in list file.

        """
        return self.inc['totim'].tolist()

    def get_kstpkper(self):
        """
        Get a list of unique stress periods and time steps in the file

        Returns
        ----------
        out : list of (kstp, kper) tuples
            List of unique kstp, kper combinations in binary file.  kstp and
            kper values are presently zero-based.

        """
        kstpkper = []
        for kstp, kper in zip(self.inc['time_step'], self.inc['stress_period']):
            kstpkper.append((kstp, kper))
        return kstpkper

    def get_dataframes(self, start_datetime="1-1-1970"):
        """
        :param start_datetime:
        :return:
        """
        try:
            import pandas as pd
        except Exception as e:
            raise Exception("ListBudget.get_dataframe() error import pandas: " + \
                            str(e))

        # so we can get a datetime index for the dataframe
        if start_datetime is not None:
            lt = ListTime(self.file_name, start=pd.to_datetime(start_datetime))
            #lt._load()
            #idx = lt.dt
        else:
            # idx = pd.MultiIndex.from_tuples(list(zip(fin["stress_period"], fin["time_step"])))
            lt = ListTime(self.file_name, start=pd.to_datetime(start_datetime))
            #lt._load()
            #idx = lt.totim
        idx = lt.get_times()

        df_flux = pd.DataFrame(self.inc, index=idx).loc[:, self.entries]

        df_vol = pd.DataFrame(self.cum, index=idx).loc[:, self.entries]
        return df_flux, df_vol


    def _build_index(self, maxentries):
        # print('building index...')
        self.idx_map = self._get_index(maxentries)
        # print('\ndone - found',len(self.idx_map),'entries')

    def _get_index(self, maxentries):
        # --parse through the file looking for matches and parsing ts and sp
        idxs = []
        l_count = 1
        while True:
            seekpoint = self.f.tell()
            line = self.f.readline()
            if line == '':
                break
            if self.lstkey in line:
                for l in range(self.tssp_lines):
                    line = self.f.readline()
                try:
                    ts, sp = self._get_ts_sp(line)
                except:
                    print('unable to cast ts,sp on line number', l_count, ' line: ', line)
                    break
                # print('info found for timestep stress period',ts,sp)

                idxs.append([ts, sp, seekpoint])

                if maxentries and len(idxs) >= maxentries:
                    break

        return idxs

    def _get_ts_sp(self, line):
        ts = int(line[self.ts_idxs[0]:self.ts_idxs[1]])
        sp = int(line[self.sp_idxs[0]:self.sp_idxs[1]])
        return ts, sp

    def _set_entries(self):
        if len(self.entries) > 0:
            raise Exception('entries already set:' + str(self.entries))
        if not self.idx_map:
            raise Exception('must call build_index before call set_entries')
        try:
            incdict, cumdict = self._get_sp(self.idx_map[0][0],
                                            self.idx_map[0][1],
                                            self.idx_map[0][2])
        except:
            raise Exception('unable to read budget information from first entry in list file')
        self.entries = incdict.keys()
        null_entries = {}
        incdict = {}
        cumdict = {}
        for entry in self.entries:
            incdict[entry] = []
            cumdict[entry] = []
            null_entries[entry] = np.NaN
        self.null_entries = [null_entries, null_entries]
        return incdict, cumdict


    def _load(self, maxentries=None):
        self._build_index(maxentries)
        incdict, cumdict = self._set_entries()
        for ts, sp, seekpoint in self.idx_map:
            tinc, tcum = self._get_sp(ts, sp, seekpoint)
            for entry in self.entries:
                incdict[entry].append(tinc[entry])
                cumdict[entry].append(tcum[entry])

        # get kstp and kper
        idx_array = np.array(self.idx_map)

        # get totime
        lt = ListTime(self.file_name, start=None)
        totim = lt.get_times()

        # build rec arrays
        dtype_tups = [('totim', np.float32), ("time_step", np.int32), ("stress_period", np.int32)]
        for entry in self.entries:
            dtype_tups.append((entry, np.float32))
        dtype = np.dtype(dtype_tups)
        nentries = len(incdict[entry])
        self.inc = np.recarray(shape=(nentries,), dtype=dtype)
        self.cum = np.recarray(shape=(nentries,), dtype=dtype)
        for entry in self.entries:
            self.inc[entry] = incdict[entry]
            self.cum[entry] = cumdict[entry]
        self.inc['totim'], self.cum['totim'] = np.array(totim)[:], np.array(totim)[:]
        self.inc["time_step"], self.inc["stress_period"] = idx_array[:, 0], idx_array[:, 1]
        self.cum["time_step"], self.cum["stress_period"] = idx_array[:, 0], idx_array[:, 1]

        return

    def _get_sp(self, ts, sp, seekpoint):
        self.f.seek(seekpoint)
        # --read to the start of the "in" budget information
        while True:
            line = self.f.readline()
            if line == '':
                # raise Exception('end of file found while seeking budget information')
                print('end of file found while seeking budget information for ts,sp', ts, sp)
                return self.null_entries

            # --if there are two '=' in this line, then it is a budget line
            if len(re.findall('=', line)) == 2:
                break

        tag = 'IN'
        incdict, cumdict = {}, {}
        while True:

            if line == '':
                # raise Exception('end of file found while seeking budget information')
                print('end of file found while seeking budget information for ts,sp', ts, sp)
                return self.null_entries
            if len(re.findall('=', line)) == 2:
                try:
                    entry, flux, cumu = self._parse_budget_line(line)
                except e:
                    print('error parsing budget line in ts,sp', ts, sp)
                    return self.null_entries
                if flux is None:
                    print('error casting in flux for', entry, ' to float in ts,sp', ts, sp)
                    return self.null_entries
                if cumu is None:
                    print('error casting in cumu for', entry, ' to float in ts,sp', ts, sp)
                    return self.null_entries
                if tag.upper() in entry:
                    if ' - ' in entry.upper():
                        key = entry.replace(' ', '')
                    else:
                        key = entry.replace(' ', '_')
                elif 'PERCENT DISCREPANCY' in entry.upper():
                    key = entry.replace(' ', '_')
                else:
                    key = '{}_{}'.format(entry.replace(' ', '_'), tag)
                incdict[key] = flux
                cumdict[key] = cumu
            else:
                if 'OUT:' in line.upper():
                    tag = 'OUT'
            line = self.f.readline()
            if entry.upper() == 'PERCENT DISCREPANCY':
                break

        return incdict, cumdict

    def _parse_budget_line(self, line):
        raw = line.strip().split()
        entry = line.strip().split('=')[0].strip()
        cu_str = line[self.cumu_idxs[0]:self.cumu_idxs[1]]
        fx_str = line[self.flux_idxs[0]:self.flux_idxs[1]]
        flux, cumu = None, None
        try:
            cumu = float(cu_str)
        except:
            if 'NAN' in cu_str.strip().upper():
                cumu = np.NaN
        try:
            flux = float(fx_str)
        except:
            if 'NAN' in fx_str.strip().upper():
                flux = np.NaN
        return entry, flux, cumu


class SwtListBudget(ListBudget):
    def __init__(self, file_name, key_string='MASS BUDGET FOR ENTIRE MODEL'):
        assert os.path.exists(file_name)
        self.file_name = file_name
        if sys.version_info[0] == 2:
            self.f = open(file_name, 'r')
        elif sys.version_info[0] == 3:
            self.f = open(file_name, 'r', encoding='ascii', errors='replace')
        # self.lstkey = re.compile(key_string)
        self.lstkey = key_string
        self.idx_map = []
        self.entries = []
        self.null_entries = []
        self.flux = {}
        self.cumu = {}
        self.cumu_idxs = [22, 40]
        self.flux_idxs = [63, 80]
        self.ts_idxs = [50, 54]
        self.sp_idxs = [70, 75]
        self.tssp_lines = 0
        # set budget recarrays
        self._load()


class MfListBudget(ListBudget):
    def __init__(self, file_name, key_string='VOLUMETRIC BUDGET FOR ENTIRE MODEL'):
        assert os.path.exists(file_name)
        self.file_name = file_name
        if sys.version_info[0] == 2:
            self.f = open(file_name, 'r')
        elif sys.version_info[0] == 3:
            self.f = open(file_name, 'r', encoding='ascii', errors='replace')
        # self.lstkey = re.compile(key_string)
        self.lstkey = key_string
        self.idx_map = []
        self.entries = []
        self.null_entries = []
        self.flux = {}
        self.cumu = {}
        self.cumu_idxs = [22, 40]
        self.flux_idxs = [63, 80]
        self.ts_idxs = [56, 61]
        self.sp_idxs = [76, 80]
        self.tssp_lines = 0
        # set budget recarrays
        self._load()


class SwrListBudget(ListBudget):
    def __init__(self, file_name, key_string='VOLUMETRIC SURFACE WATER BUDGET FOR ENTIRE MODEL'):
        assert os.path.exists(file_name)
        self.file_name = file_name
        if sys.version_info[0] == 2:
            self.f = open(file_name, 'r')
        elif sys.version_info[0] == 3:
            self.f = open(file_name, 'r', encoding='ascii', errors='replace')
        # self.lstkey = re.compile(key_string)
        self.lstkey = key_string
        self.idx_map = []
        self.entries = []
        self.null_entries = []
        self.flux = {}
        self.cumu = {}
        self.cumu_idxs = [25, 43]
        self.flux_idxs = [66, 84]
        self.ts_idxs = [39, 46]
        self.sp_idxs = [62, 68]
        self.tssp_lines = 1
        # set budget recarrays
        self._load()


class ListTime(ListBudget):
    '''class to extract time information from lst file
    passing a start datetime results in casting the totim to dts from start
    '''

    def __init__(self, file_name, timeunit='days', key_str='TIME SUMMARY AT END',
                 start=None, flow=True):

        assert os.path.exists(file_name)
        self.file_name = file_name
        if sys.version_info[0] == 2:
            self.f = open(file_name, 'r')
        elif sys.version_info[0] == 3:
            self.f = open(file_name, 'r', encoding='ascii', errors='replace')
        self.idx_map = []
        self.tslen = []
        self.sptim = []
        self.totim = []
        # self.lstkey = re.compile(key_str)
        self.lstkey = key_str
        self.tssp_lines = 0
        if flow:
            self.ts_idxs = [42, 47]
            self.sp_idxs = [63, 69]
        else:
            self.ts_idxs = [65, 71]
            self.sp_idxs = [87, 92]
        self.time_line_idx = 20
        if timeunit.upper() == 'DAYS':
            self.timeunit = 'D'
            self.time_idx = 3
        else:
            raise Exception('need to reset time_idxs attribute to " +\
            "use units other than days and check usage of timedelta')
        self.null_entries = [np.NaN, np.NaN, np.NaN]
        self.start = start
        if start:
            self.dt = []

        # load the data
        self._load()


    def get_times(self):
        """
        Get a list of unique water budget times in the list file

        Returns
        ----------
        out : list of floats
            List contains unique water budget simulation times (totim) in list file.

        """
        return self.totim


    def _load(self, maxentries=None):
        self._build_index(maxentries)

        for i, [ts, sp, seekpoint] in enumerate(self.idx_map):
            # print 'loading stress period, timestep',sp,ts,

            tslen, sptim, totim = self._get_sp(ts, sp, seekpoint)
            self.tslen.append(tslen)
            self.sptim.append(sptim)
            self.totim.append(totim)
        if self.start is not None:
            self.dt = self.cast_totim()
        return

    def _cast_totim(self):
        if self.timeunit == 'D':
            totim = []
            for to in self.totim:
                t = timedelta(days=to)
                totim.append(self.start + t)
        return totim

    def _get_sp(self, ts, sp, seekpoint):
        self.f.seek(seekpoint)
        # --read header lines
        ihead = 0
        while True:
            line = self.f.readline()
            ihead += 1
            if line == '':
                # raise Exception('end of file found while seeking budget information')
                print('end of file found while seeking time information for ts,sp', ts, sp)
                return self.null_entries
            elif ihead == 2 and 'SECONDS     MINUTES      HOURS       DAYS        YEARS' not in line:
                break
            elif '-----------------------------------------------------------' in line:
                line = self.f.readline()
                break
        tslen = self._parse_time_line(line)
        if tslen == None:
            print('error parsing tslen for ts,sp', ts, sp)
            return self.null_entries

        sptim = self._parse_time_line(self.f.readline())
        if sptim == None:
            print('error parsing sptim for ts,sp', ts, sp)
            return self.null_entries

        totim = self._parse_time_line(self.f.readline())
        if totim == None:
            print('error parsing totim for ts,sp', ts, sp)
            return self.null_entries
        return tslen, sptim, totim

    def _parse_time_line(self, line):
        if line == '':
            print('end of file found while parsing time information')
            return None
        try:
            time_str = line[self.time_line_idx:]
            raw = time_str.split()
            idx = self.time_idx
            # catch case where itmuni is undefined
            # in this case, the table format is different
            try:
                v = float(raw[0])
            except:
                time_str = line[45:]
                raw = time_str.split()
                idx = 0
            tval = float(raw[idx])
        except:
            print('error parsing tslen information', time_str)
            return None
        return tval
