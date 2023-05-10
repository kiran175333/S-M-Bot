from re import match as re_match, findall as re_findall
from os import path as ospath, rename as osrename
from threading import Thread, Event
from time import time
from datetime import datetime
from math import ceil
from html import escape
from psutil import cpu_percent, disk_usage, net_io_counters, virtual_memory
from requests import head as rhead
from urllib.request import urlopen

from bot.helper.ext_utils.db_handler import DbManger
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot import LOGGER, CATEGORY_IDS, CATEGORY_INDEX, CATEGORY_NAMES, DATABASE_URL, dispatcher, download_dict, \
                download_dict_lock, botStartTime, DOWNLOAD_DIR, user_data, config_dict
from telegram.ext import CallbackQueryHandler


MAGNET_REGEX = r'magnet:\?xt=urn:(btih|btmh):[a-zA-Z0-9]*\s*'

URL_REGEX = r'^(?!\/)(rtmps?:\/\/|mms:\/\/|rtsp:\/\/|https?:\/\/|ftp:\/\/)?([^\/:]+:[^\/@]+@)?(www\.)?(?=[^\/:\s]+\.[^\/:\s]+)([^\/:\s]+\.[^\/:\s]+)(:\d+)?(\/[^#\s]*[\s\S]*)?(\?[^#\s]*)?(#.*)?$'

COUNT = 0
PAGE_NO = 1
PAGES = 0


class MirrorStatus:
    STATUS_UPLOADING = "Uploading"
    STATUS_DOWNLOADING = "Downloading"
    STATUS_CLONING = "Cloning"
    STATUS_QUEUEDL = "Queue Download"
    STATUS_QUEUEUP = "Queue Upload"
    STATUS_PAUSED = "Paused"
    STATUS_ARCHIVING = "Archiving"
    STATUS_EXTRACTING = "Extracting"
    STATUS_SPLITTING = "Splitting"
    STATUS_CHECKING = "CheckUp"
    STATUS_SEEDING = "Seeding"
    STATUS_CONVERTING = "Converting"

class EngineStatus:
    STATUS_ARIA = "Aria2c"
    STATUS_GD = "Google Api"
    STATUS_MEGA = "MegaSDK"
    STATUS_QB = "qBittorrent"
    STATUS_TG = "Pyrogram"
    STATUS_YT = "YT-dlp"
    STATUS_EXT = "pExtract"
    STATUS_SPLIT_MERGE = "FFmpeg"
    STATUS_ZIP = "p7zip"
    STATUS_QUEUE = "Sleep"

    
SIZE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']

class setInterval:
    def __init__(self, interval, action):
        self.interval = interval
        self.action = action
        self.stopEvent = Event()
        thread = Thread(target=self.__setInterval)
        thread.start()

    def __setInterval(self):
        nextTime = time() + self.interval
        while not self.stopEvent.wait(nextTime - time()):
            self.action()
            nextTime = time() + self.interval

    def cancel(self):
        self.stopEvent.set()

def get_readable_file_size(size_in_bytes) -> str:
    if size_in_bytes is None:
        return '0B'
    index = 0
    while size_in_bytes >= 1024:
        size_in_bytes /= 1024
        index += 1
    try:
        return f'{round(size_in_bytes, 2)}{SIZE_UNITS[index]}'
    except IndexError:
        return 'File too large'

def getDownloadByGid(gid):
    with download_dict_lock:
        for dl in list(download_dict.values()):
            if dl.gid() == gid:
                return dl
    return None

def getAllDownload(req_status: str):
    with download_dict_lock:
        for dl in list(download_dict.values()):
            status = dl.status()
            if req_status in ['all', status]:
                return dl
    return None

def bt_selection_buttons(id_: str):
    gid = id_[:12] if len(id_) > 20 else id_

    pincode = ""
    for n in id_:
        if n.isdigit():
            pincode += str(n)
        if len(pincode) == 4:
            break

    buttons = ButtonMaker()
    BASE_URL = config_dict['BASE_URL']
    if config_dict['WEB_PINCODE']:
        buttons.buildbutton("Select Files", f"{BASE_URL}/app/files/{id_}")
        buttons.sbutton("Pincode", f"btsel pin {gid} {pincode}")
    else:
        buttons.buildbutton("Select Files", f"{BASE_URL}/app/files/{id_}?pin_code={pincode}")
    buttons.sbutton("Done Selecting", f"btsel done {gid} {id_}")
    return buttons.build_menu(2)


def get_user_task(user_id):
    user_task = 0
    for task in list(download_dict.values()):
        userid = task.message.from_user.id
        if userid == user_id: user_task += 1
    return user_task

def get_bot_pm(user_id):
    if config_dict['FORCE_BOT_PM']:
        return True
    else:
        if not (user_id in user_data and user_data[user_id].get('ubot_pm')):
            update_user_ldata(user_id, 'ubot_pm', config_dict['BOT_PM'])
        botpm = user_data[user_id].get('ubot_pm')
        return botpm

def getGDriveUploadUtils(user_id, u_index, c_index):
    GDRIVEID = config_dict['GDRIVE_ID']
    INDEXURL = config_dict['INDEX_URL']
    if u_index is not None:
        _, GDriveID, IndexURL = getUserTDs(user_id)
        GDRIVEID = GDriveID[u_index]
        INDEXURL = IndexURL[u_index]
    elif c_index != 0:
        GDRIVEID = CATEGORY_IDS[c_index]
        INDEXURL = CATEGORY_INDEX[c_index]
    return GDRIVEID, INDEXURL

def getUserTDs(user_id, force=False):
    GDriveID, IndexURL, GDNames = [], [], []
    if user_id in user_data and (user_data[user_id].get('is_usertd') or force) and user_data[user_id].get('usertd'):
        LOGGER.info("Using USER TD!")
        userDest = (user_data[user_id].get('usertd')).split('\n')
        if len(userDest) != 0:
            for i, _ in enumerate(userDest):
                arrForUser = userDest[i].split()
                GDNames.append(arrForUser[0])
                GDriveID.append(arrForUser[1])
                IndexURL.append(arrForUser[2].rstrip('/') if len(arrForUser) > 2 else '')
    return GDNames, GDriveID, IndexURL

def handleIndex(index, dic):
    """Handle IndexError for any List (Runs Index Loop) +ve & -ve Supported"""
    while True:
        if abs(index) >= len(dic):
            if index < 0: index = len(dic) - abs(index)
            elif index > 0: index = index - len(dic)
        else: break
    return index

  
def userlistype(user_id):
    user_dict = user_data.get(user_id, False)
    if user_dict and user_dict.get("ulist_typ"):
        tegr = user_dict.get("ulist_typ") == "Telegraph"
        html = user_dict.get("ulist_typ") == "HTML"
        tgdi = user_dict.get("ulist_typ") == "Tele_Msg"
    else:
        tegr = config_dict['LIST_MODE'].lower() == "telegraph"
        html = config_dict['LIST_MODE'].lower() == "html"
        tgdi = config_dict['LIST_MODE'].lower() == "tg_direct"
    return tegr, html, tgdi

def progress_bar(percentage):
    """Returns a progress bar for download"""
    if isinstance(percentage, str):
        return "N/A"
    try:
        percentage = int(percentage)
    except Exception:
        percentage = 0
    comp = "▰"
    ncomp = "▱"
    return "".join(comp if i <= percentage // 10 else ncomp for i in range(1, 11))

def timeformatter(milliseconds: int) -> str:
    seconds, milliseconds = divmod(int(milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    tmp = ((str(days) + " days, ") if days else "") + \
        ((str(hours) + " hours, ") if hours else "") + \
        ((str(minutes) + " min, ") if minutes else "") + \
        ((str(seconds) + " sec, ") if seconds else "") + \
        ((str(milliseconds) + " millisec, ") if milliseconds else "")
    return tmp[:-2]

def get_progress_bar_string(status):
    completed = status.processed_bytes() / 8
    total = status.size_raw() / 8
    p = 0 if total == 0 else round(completed * 100 / total)
    p = min(max(p, 0), 100)
    cFull = p // 8
    cPart = p % 8 - 1
    p_str = config_dict['FINISHED_PROGRESS_STR'] * cFull
    if cPart >= 0:
        p_str += config_dict['MULTI_WORKING_PROGRESS_STR'][cPart]
    p_str += config_dict['UN_FINISHED_PROGRESS_STR']  * (12 - cFull)
    return f"{p_str}"


def get_readable_message():
    msg = "<b>Powered by Luna</b>\n\n"
    button = None
    STATUS_LIMIT = config_dict['STATUS_LIMIT']
    tasks = len(download_dict)
    globals()['PAGES'] = (tasks + STATUS_LIMIT - 1) // STATUS_LIMIT
    if PAGE_NO > PAGES and PAGES != 0:
        globals()['STATUS_START'] = STATUS_LIMIT * (PAGES - 1)
        globals()['PAGE_NO'] = PAGES
    for download in list(download_dict.values())[STATUS_START:STATUS_LIMIT+STATUS_START]:
        msg += f"<i>{escape(f'{download.name()}')}</i>\n\n"
        msg += f"<b>┌ {download.status()} with {download.engine}</b>"
        if download.status() not in [MirrorStatus.STATUS_SPLITTING, MirrorStatus.STATUS_SEEDING]:
            msg += f"\n<b>├ <a href='https://github.com/5hojib/Luna'>{get_progress_bar_string(download.progress())}</a></b> {download.progress()}"
            msg += f"\n<b>├ </b>{download.processed_bytes()} of {download.size()}"
            msg += f"\n<b>├ Speed</b>: {download.speed()}"
            msg += f'\n<b>├ Estimated</b>: {download.eta()}'
            if hasattr(download, 'seeders_num'):
                try:
                    msg += f"\n<b>├ Seeders</b>: {download.seeders_num()} | <b>Leechers</b>: {download.leechers_num()}"
                except:
                    pass
        elif download.status() == MirrorStatus.STATUS_SEEDING:
            msg += f"\n<b>├ Size</b>: {download.size()}"
            msg += f"\n<b>├ Speed</b>: {download.upload_speed()}"
            msg += f"\n<b>├ Uploaded</b>: {download.uploaded_bytes()}"
            msg += f"\n<b>├ Ratio</b>: {download.ratio()}"
            msg += f"\n<b>├ Time</b>: {download.seeding_time()}"
        else:
            msg += f"\n<b>├ Size</b>: {download.size()}"
        msg += f"\n<b>├ Elapsed</b>: {get_readable_time(time() - download.extra_details['startTime'])}"
        msg += f"\n<b>├ Source</b>: {download.extra_details['source']}"
        msg += f"\n<b>└ </b><code>/{BotCommands.CancelMirror} {download.gid()}</code>\n\n"
    if len(msg) == 0:
        return None, None
    dl_speed = 0
    up_speed = 0
    for download in download_dict.values():
            tstatus = download.status()
            if tstatus == MirrorStatus.STATUS_DOWNLOADING:
                spd = download.speed()
                if 'K' in spd:
                    dl_speed += float(spd.split('K')[0]) * 1024
                elif 'M' in spd:
                    dl_speed += float(spd.split('M')[0]) * 1048576
            elif tstatus == MirrorStatus.STATUS_UPLOADING:
                spd = download.speed()
                if 'K' in spd:
                    up_speed += float(spd.split('K')[0]) * 1024
                elif 'M' in spd:
                    up_speed += float(spd.split('M')[0]) * 1048576
            elif tstatus == MirrorStatus.STATUS_SEEDING:
                spd = download.upload_speed()
                if 'K' in spd:
                    up_speed += float(spd.split('K')[0]) * 1024
                elif 'M' in spd:
                    up_speed += float(spd.split('M')[0]) * 1048576
    if tasks > STATUS_LIMIT:
        buttons = ButtonMaker()
        buttons.ibutton("Prev", "status pre")
        buttons.ibutton(f"{PAGE_NO}/{PAGES}", "status ref")
        buttons.ibutton("Next", "status nex")
        button = buttons.build_menu(3)
    msg += f"<b>• Tasks running</b>: {tasks}"
    msg += f"\n<b>• Free disk space</b>: {get_readable_file_size(disk_usage(config_dict['DOWNLOAD_DIR']).free)}"
    msg += f"\n<b>• Uploading speed</b>: {get_readable_file_size(up_speed)}/s"
    msg += f"\n<b>• Downloading speed</b>: {get_readable_file_size(dl_speed)}/s"
    return msg, button

async def turn_page(data):
    STATUS_LIMIT = config_dict['STATUS_LIMIT']
    global STATUS_START, PAGE_NO
    async with download_dict_lock:
        if data[1] == "nex":
            if PAGE_NO == PAGES:
                STATUS_START = 0
                PAGE_NO = 1
            else:
                STATUS_START += STATUS_LIMIT
                PAGE_NO += 1
        elif data[1] == "pre":
            if PAGE_NO == 1:
                STATUS_START = STATUS_LIMIT * (PAGES - 1)
                PAGE_NO = PAGES
            else:
                STATUS_START -= STATUS_LIMIT
                PAGE_NO -= 1

def get_readable_time(seconds: int) -> str:
    result = ''
    (days, remainder) = divmod(seconds, 86400)
    days = int(days)
    if days != 0:
        result += f'{days} Days '
    (hours, remainder) = divmod(remainder, 3600)
    hours = int(hours)
    if hours != 0:
        result += f'{hours} Hours '
    (minutes, seconds) = divmod(remainder, 60)
    minutes = int(minutes)
    if minutes != 0:
        result += f'{minutes} Min '
    seconds = int(seconds)
    result += f'{seconds} Sec'
    return result

def is_url(url: str):
    url = re_findall(URL_REGEX, url)
    return bool(url)

def is_gdrive_link(url: str):
    return "drive.google.com" in url

def is_gdtot_link(url: str):
    url = re_match(r'https?://.+\.gdtot\.\S+', url)
    return bool(url)

def is_udrive_link(url: str):
    if 'drivehub.ws' in url:
        return 'drivehub.ws' in url
    else:
        url = re_match(r'https?://(hubdrive|katdrive|kolop|drivefire)\.\S+', url)
        return bool(url)

def is_unified_link(url: str):
    url1 = re_match(r'https?://(anidrive|driveroot|driveflix|indidrive|drivehub)\.in/\S+', url)
    url = re_match(r'https?://(appdrive|driveapp|driveace|gdflix|drivelinks|drivebit|drivesharer|drivepro|driveseed|driveleech)\.\S+', url)
    if bool(url1) == True:
        return bool(url1)
    elif bool(url) == True:
        return bool(url)
    else:
        return False

    
def is_sharer_link(url: str):
    url = re_match(r'https?://(sharer)\.pw/\S+', url)
    return bool(url)

def is_sharedrive_link(url: str):
    url = re_match(r'https?://(sharedrive)\.\S+', url)
    return bool(url)

def is_filepress_link(url: str):
    url = re_match(r'https?://(filepress|filebee)\.\S+', url)
    return bool(url)

def is_mega_link(url: str):
    return "mega.nz" in url or "mega.co.nz" in url

def get_mega_link_type(url: str):
    if "folder" in url:
        return "folder"
    elif "file" in url:
        return "file"
    elif "/#F!" in url:
        return "folder"
    return "file"

def is_magnet(url: str):
    magnet = re_findall(MAGNET_REGEX, url)
    return bool(magnet)

def new_thread(fn):
    """To use as decorator to make a function call threaded.
    Needs import
    from threading import Thread"""

    def wrapper(*args, **kwargs):
        thread = Thread(target=fn, args=args, kwargs=kwargs)
        thread.start()
        return thread

    return wrapper

def get_content_type(link: str) -> str:
    try:
        res = rhead(link, allow_redirects=True, timeout=5, headers = {'user-agent': 'Wget/1.12'})
        content_type = res.headers.get('content-type')
    except:
        try:
            res = urlopen(link, timeout=5)
            info = res.info()
            content_type = info.get_content_type()
        except:
            content_type = None
    return content_type

def change_filename(file_, user_id_, dirpath=None, up_path=None, all_edit=True, mirror_type=False):
    user_dict = user_data.get(user_id_, False)
    if mirror_type:
        PREFIX = user_dict.get('mprefix') if user_dict and user_dict.get('mprefix') else ''
        REMNAME = user_dict.get('mremname') if user_dict and user_dict.get('mremname') else ''
        SUFFIX = user_dict.get('msuffix') if user_dict and user_dict.get('msuffix') else ''
    else:
        PREFIX = user_dict.get('prefix') if user_dict and user_dict.get('prefix') else ''
        REMNAME = user_dict.get('remname') if user_dict and user_dict.get('remname') else ''
        SUFFIX = user_dict.get('suffix') if user_dict and user_dict.get('suffix') else ''

    FSTYLE = user_dict.get('cfont')[1] if user_dict and user_dict.get('cfont') else ''
    CAPTION = user_dict.get('caption') if user_dict and user_dict.get('caption') else ''

    #MysteryStyle ~ Tele-LeechX
    if file_.startswith('www'):
        file_ = ' '.join(file_.split()[1:])
    if REMNAME:
        if not REMNAME.startswith('|'):
            REMNAME = f"|{REMNAME}"
        REMNAME = REMNAME.replace('\s', ' ')
        slit = REMNAME.split("|")
        __newFileName = ospath.splitext(file_)[0]
        for rep in range(1, len(slit)):
            args = slit[rep].split(":")
            if len(args) == 3:
                __newFileName = __newFileName.replace(args[0], args[1], int(args[2]))
            elif len(args) == 2:
                __newFileName = __newFileName.replace(args[0], args[1])
            elif len(args) == 1:
                __newFileName = __newFileName.replace(args[0], '')
        file_ = __newFileName + ospath.splitext(file_)[1]
        LOGGER.info("Remname : "+file_)
    if PREFIX:
        PREFIX = PREFIX.replace('\s', ' ')
        if not file_.startswith(PREFIX):
            file_ = f"{PREFIX}{file_}"
    if SUFFIX and not mirror_type:
        SUFFIX = SUFFIX.replace('\s', ' ')
        sufLen = len(SUFFIX)
        fileDict = file_.split('.')
        _extIn = 1 + len(fileDict[-1])
        _extOutName = '.'.join(fileDict[:-1]).replace('.', ' ').replace('-', ' ')
        _newExtFileName = f"{_extOutName}{SUFFIX}.{fileDict[-1]}"
        if len(_extOutName) > (64 - (sufLen + _extIn)):
            _newExtFileName = (
                _extOutName[: 64 - (sufLen + _extIn)]
                + f"{SUFFIX}.{fileDict[-1]}"
            )
        file_ = _newExtFileName
    elif SUFFIX:
        SUFFIX = SUFFIX.replace('\s', ' ')
        file_ = f"{ospath.splitext(file_)[0]}{SUFFIX}{ospath.splitext(file_)[1]}" if '.' in file_ else f"{file_}{SUFFIX}"

    if (PREFIX or REMNAME or SUFFIX) and all_edit:
        new_path = ospath.join(dirpath, file_)
        osrename(up_path, new_path)
        up_path = new_path

    cap_mono = ""
    cfont = config_dict['CAPTION_FONT'] if not FSTYLE else FSTYLE
    if CAPTION and all_edit:
        CAPTION = CAPTION.replace('\|', '%%').replace('\s', ' ')
        slit = CAPTION.split("|")
        cap_mono = slit[0].format(
            filename = file_,
            size = get_readable_file_size(ospath.getsize(up_path))
        )
        if len(slit) > 1:
            for rep in range(1, len(slit)):
                args = slit[rep].split(":")
                if len(args) == 3:
                   cap_mono = cap_mono.replace(args[0], args[1], int(args[2]))
                elif len(args) == 2:
                    cap_mono = cap_mono.replace(args[0], args[1])
                elif len(args) == 1:
                    cap_mono = cap_mono.replace(args[0], '')
        cap_mono = cap_mono.replace('%%', '|')
    elif all_edit:
        cap_mono = file_ if FSTYLE == 'r' else f"<{cfont}>{file_}</{cfont}>"

    return up_path, file_, cap_mono

def update_user_ldata(id_, key, value):
    if id_ in user_data:
        user_data[id_][key] = value
    else:
        user_data[id_] = {key: value}

def is_sudo(user_id):
    if user_id in user_data:
        return user_data[user_id].get('is_sudo')
    return False

def getdailytasks(user_id, increase_task=False, upleech=0, upmirror=0, check_mirror=False, check_leech=False):
    task, lsize, msize = 0, 0, 0
    if user_id in user_data and user_data[user_id].get('dly_tasks'):
        userdate = user_data[user_id]['dly_tasks'][0]
        nowdate = datetime.today()
        if userdate.year <= nowdate.year and userdate.month <= nowdate.month and userdate.day < nowdate.day:
            if increase_task: task = 1
            elif upleech != 0: lsize += upleech #bytes
            elif upmirror != 0: msize += upmirror #bytes
            update_user_ldata(user_id, 'dly_tasks', [datetime.today(), task, lsize, msize])
            if DATABASE_URL:
                DbManger().update_user_data(user_id)
            if check_leech: return lsize
            elif check_mirror: return msize
            return task
        else:
            task = user_data[user_id]['dly_tasks'][1]
            lsize = user_data[user_id]['dly_tasks'][2]
            msize = user_data[user_id]['dly_tasks'][3]
            if increase_task: task += 1
            elif upleech != 0: lsize += upleech
            elif upmirror != 0: msize += upmirror
            if increase_task or upleech or upmirror:
                update_user_ldata(user_id, 'dly_tasks', [datetime.today(), task, lsize, msize])
                if DATABASE_URL:
                    DbManger().update_user_data(user_id)
            if check_leech: return lsize
            elif check_mirror: return msize
            return task
    else:
        if increase_task: task += 1
        elif upleech != 0: lsize += upleech
        elif upmirror != 0: msize += upmirror
        update_user_ldata(user_id, 'dly_tasks', [datetime.today(), task, lsize, msize])
        if DATABASE_URL:
            DbManger().update_user_data(user_id)
        if check_leech: return lsize
        elif check_mirror: return msize
        return task

def is_paid(user_id):
    if config_dict['PAID_SERVICE'] is True:
        if user_id in user_data and user_data[user_id].get('is_paid'):
            ex_date = user_data[user_id].get('expiry_date')
            if ex_date:
                odate = datetime.strptime(ex_date, '%d-%m-%Y')
                ndate = datetime.today()
                if odate.year <= ndate.year and odate.month <= ndate.month and odate.day < ndate.day:
                    return False
            return True
        else: return False
    else: return False

ONE, TWO, THREE = range(3)
def pop_up_stats(update, context):
    query = update.callback_query
    stats = bot_sys_stats()
    query.answer(text=stats, show_alert=True)
def bot_sys_stats():
    recv = get_readable_file_size(net_io_counters().bytes_recv)
    sent = get_readable_file_size(net_io_counters().bytes_sent)
    num_active = 0
    num_upload = 0
    num_seeding = 0
    num_zip = 0
    num_unzip = 0
    num_split = 0
    tasks = len(download_dict)
    cpu = cpu_percent()
    mem = virtual_memory().percent
    disk = disk_usage("/").percent
    for stats in list(download_dict.values()):
        if stats.status() == MirrorStatus.STATUS_DOWNLOADING:
            num_active += 1
        if stats.status() == MirrorStatus.STATUS_UPLOADING:
            num_upload += 1
        if stats.status() == MirrorStatus.STATUS_SEEDING:
            num_seeding += 1
        if stats.status() == MirrorStatus.STATUS_ARCHIVING:
            num_zip += 1
        if stats.status() == MirrorStatus.STATUS_EXTRACTING:
            num_unzip += 1
        if stats.status() == MirrorStatus.STATUS_SPLITTING:
            num_split += 1
    return f"""
Modified by Chishiya.

Tasks: {tasks}

CPU: {cpu}%
RAM: {mem}%
DISK: {disk}%

SENT DATA: {sent}
RECEIVED DATA: {recv}

Downloads: {num_active}
Uploads: {num_upload} | SEEDING: {num_seeding}
ZIP: {num_zip}
UNZIP: {num_unzip}
"""
    return stats
dispatcher.add_handler(
    CallbackQueryHandler(pop_up_stats, pattern="^" + str(THREE) + "$")
)
