import yaml
import re
import logging
import types

log = logging.getLogger('modify_torrent')


# Torrent decoding is a short fragment from effbot.org. Site copyright says:
# Test scripts and other short code fragments can be considered as being in the public domain.

class Torrent:
    """Represents a torrent"""

    def __init__(self, content):
        """Accepts torrent file as string"""
        
        # valid torrent files start with an announce block
        if not content.startswith("d8:announce"):
            raise Exception('Invalid content for a torrent')

        self.encode_func = {}
        self.encode_func[type(str())] = self.encode_string
        self.encode_func[type(int())] = self.encode_integer
        self.encode_func[type(long())] = self.encode_integer
        self.encode_func[type(list())] = self.encode_list
        self.encode_func[type(dict())] = self.encode_dictionary

        # decoded torrent structure
        self.content = self.decode(content)

    def get_filelist(self):
        """Return array containing fileinfo dictionaries (name, length, path)"""
        files = []
        # single file torrent
        if self.content["info"].has_key("length"):
            t = {}
            t["name"] = self.content["info"]["name"]
            t["size"] = self.content["info"]["length"]
            t["path"] = ""
            files.append(t)
        else:
            # multifile torrent
            for item in self.content["info"]["files"]:
                t = {}
                import string
                t['path'] = string.join(item['path'][:-1], '/')
                t['name'] = item['path'][-1:]
                t['size'] = item['length']
                files.append(t)
        return files

    def get_multitrackers(self):
        """
        Return array containing all multi-trackers in this torrent.
        Returns empty array if torrent has only standard single announce url.
        """
        trackers = []
        # the spec says, if announce-list present use ONLY that
        # funny iteration because of nesting, ie:
        # [ [ tracker1, tracker2 ], [backup1] ]
        for tl in self.content.get('announce-list', []):
            for t in tl: trackers.append(t)
        return trackers

    def remove_multitracker(self, tracker):
        """Removes passed multi-tracker from this torrent"""
        for tl in self.content.get('announce-list', [])[:]:
            try:
                tl.remove(tracker)
                # if no trackers left in list, remove whole list
                if len(tl)==0:
                    self.content['announce-list'].remove(tl)
            except:
                pass

    def add_multitracker(self, tracker):
        """Appends multi-tracker to this torrent"""
        self.content.setdefault('announce-list', [])
        self.content['announce-list'].append(tracker)

    def __str__(self):
        return 'Torrent instance. Files: %s' % self.get_filelist()
        
    def tokenize(self, text, match=re.compile("([idel])|(\d+):|(-?\d+)").match):
        i = 0
        while i < len(text):
            m = match(text, i)
            s = m.group(m.lastindex)
            i = m.end()
            if m.lastindex == 2:
                yield "s"
                yield text[i:i+int(s)]
                i = i + int(s)
            else:
                yield s

    def decode_item(self, next, token):
        if token == "i":
            # integer: "i" value "e"
            data = int(next())
            if next() != "e":
                raise ValueError
        elif token == "s":
            # string: "s" value (virtual tokens)
            data = next()
        elif token == "l" or token == "d":
            # container: "l" (or "d") values "e"
            data = []
            tok = next()
            while tok != "e":
                data.append(self.decode_item(next, tok))
                tok = next()
            if token == "d":
                data = dict(zip(data[0::2], data[1::2]))
        else:
            raise ValueError
        return data

    def decode(self, text):
        try:
            src = self.tokenize(text)
            data = self.decode_item(src.next, src.next())
            for token in src: # look for more tokens
                raise SyntaxError("trailing junk")
        except (AttributeError, ValueError, StopIteration):
            raise SyntaxError("syntax error")
        return data

    # encoding implementation by d0b
    
    def encode_string(self, data):
        return "%d:%s" % (len(data), data)

    def encode_integer(self, data):
        return "i%de" % data

    def encode_list(self, data):
        encoded = "l"
        for item in data:
            encoded += self.encode_func[type(item)](item)
        encoded += "e"
        return encoded

    def encode_dictionary(self, data):
        encoded = "d"
        items = data.items()
        items.sort()
        for (key, value) in items:
            encoded += self.encode_string(key)
            encoded += self.encode_func[type(value)](value)
        encoded += "e"
        return encoded

    def encode(self):
        data = self.content
        return self.encode_func[type(data)](data)
            

class TorrentFilename:

    """
        Makes sure that entries containing torrent-file have .torrent
        extension. This is enabled always by default (builtins).
    """

    def register(self, manager, parser):
        manager.register(instance=self, event='modify', keyword='torrent', callback=self.run, order=-200, builtin=True)

    def run(self, feed):
        for entry in feed.entries:
            # create torrent object from torrent & match data
            try:
                torrent = Torrent(entry.get('data', ''))
                entry['torrent'] = torrent
                entry['filename'] = self.make_filename(torrent, entry)
            except:
                # not a torrent file, no need to mess with it
                pass

    def make_filename(self, torrent, entry):
        """Build a filename for this torrent"""
        
        title = entry['title']
        files = torrent.get_filelist()
        if len(files) == 1 :
            # single file, if filename is longer than title use it
            fn = files[0]["name"]
            if len(fn) > len(title):
                title = fn[:fn.rfind('.')]
        else:
            # create a proper filename from crap we got from the feed
            title = title.replace("/", "_")

        # neatify further
        title = title.replace(" ", "_")
        title = title.encode('iso8859-1', 'ignore') # Damn \u200b -character, how I loathe thee

        return title+".torrent"

if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.DEBUG)

    from test_tools import MockFeed
    feed = MockFeed()

    f=open(sys.argv[1], 'r')
    content = f.read()
    f.close()

    entry = {}
    entry['url'] = 'http://127.0.0.1/mock'
    entry['title'] = sys.argv[2]
    entry['data'] = content

    feed.entries.append(entry)

    r = TorrentFilename()
    r.run(feed)

    trackers = entry['torrent'].get_multitrackers()

    print trackers
    entry['torrent'].remove_multitracker(trackers[0])
    print entry['torrent'].get_multitrackers()

    print yaml.safe_dump(entry['torrent'].content['announce-list'])
    
    feed.dump_entries()

