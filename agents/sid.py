# sid: an adaptive hold'em agent.
#
# Every seat gets a running profile built from the actions it takes: how often it folds,
# calls, or raises at each preflop level, how often it calls off its stack, and how it bets
# after the flop. Those frequencies turn into ranges (a seat that shoves every hand has a
# random shoving range, a seat that raises 5% of hands does not). A second number per seat
# says how much it plays its cards at all; showdowns and its betting shape move that number.
# Every option is then scored in chips and the best one is played.
#
# Preflop runs on precomputed equity tables so it answers in well under a millisecond.
# After the flop it runs a Monte Carlo against the modeled ranges for a slice of the clock.

import base64
import random
import time
import zlib

# alpha < 1 values chips slightly concavely, so a thin edge isn't worth flipping the whole stack.
# Blinds double every 3 hands, so waiting for a better spot is expensive; keep it close to 1.
TUNE = {"alpha": 0.9, "learn": True}

RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
RANK_OF = {r: i for i, r in enumerate(RANKS)}
SUIT_OF = {s: i for i, s in enumerate("♠♥♦♣")}


def card_id(text):
    return RANK_OF[text[:-1]] * 4 + SUIT_OF[text[-1]]


# ---------------------------------------------------------------- evaluator
# A card is rank * 4 + suit. Rank counts pack into 3 bits per rank and suit counts into
# 4 bits per suit, so a hand without a flush is one dict lookup on the summed rank key.

RK = [1 << (3 * (c >> 2)) for c in range(52)]
SK = [1 << (4 * (c & 3)) for c in range(52)]
RB = [1 << (c >> 2) for c in range(52)]
FLUSH_ADD = 0x3333  # a suit nibble of 5 or more carries into bit 3 of that nibble
FLUSH_BITS = 0x8888


def _code(category, ranks):
    value = category
    for i in range(5):
        value = (value << 4) | (ranks[i] if i < len(ranks) else 0)
    return value


def _straight_top(mask):
    for top in range(12, 3, -1):
        run = 0b11111 << (top - 4)
        if (mask & run) == run:
            return top
    if (mask & 0b1000000001111) == 0b1000000001111:
        return 3
    return -1


def _four_of_five(mask):
    windows = [0b11111 << low for low in range(9)] + [0b1000000001111]
    return any(bin(mask & w).count("1") >= 4 for w in windows)


STRAIGHT_TOP = [_straight_top(m) for m in range(8192)]
STRAIGHT_DRAW = [_four_of_five(m) for m in range(8192)]
FLUSH_VALUE = [0] * 8192
for _m in range(8192):
    if bin(_m).count("1") >= 5:
        _top = STRAIGHT_TOP[_m]
        if _top >= 0:
            FLUSH_VALUE[_m] = _code(8, [_top])
        else:
            FLUSH_VALUE[_m] = _code(5, [r for r in range(12, -1, -1) if _m >> r & 1][:5])


def _plain_value(counts):
    present = [r for r in range(12, -1, -1) if counts[r]]
    mask = 0
    for r in present:
        mask |= 1 << r
    quads = [r for r in present if counts[r] == 4]
    trips = [r for r in present if counts[r] == 3]
    pairs = [r for r in present if counts[r] == 2]
    if quads:
        q = quads[0]
        return _code(7, [q] + [r for r in present if r != q][:1])
    if trips and (len(trips) > 1 or pairs):
        t = trips[0]
        return _code(6, [t, max(trips[1:] + pairs)])
    top = STRAIGHT_TOP[mask]
    if top >= 0:
        return _code(4, [top])
    if trips:
        t = trips[0]
        return _code(3, [t] + [r for r in present if r != t][:2])
    if len(pairs) >= 2:
        a, b = pairs[0], pairs[1]
        return _code(2, [a, b] + [r for r in present if r != a and r != b][:1])
    if pairs:
        p = pairs[0]
        return _code(1, [p] + [r for r in present if r != p][:3])
    return _code(0, present[:5])


def _build_plain():
    table = {}
    counts = [0] * 13

    def walk(rank, total, key):
        if rank == 13:
            if total >= 5:
                table[key] = _plain_value(counts)
            return
        for c in range(min(4, 7 - total) + 1):
            counts[rank] = c
            walk(rank + 1, total + c, key + (c << (3 * rank)))
        counts[rank] = 0

    walk(0, 0, 0)
    return table


PLAIN = _build_plain()


def _flush_value(cards, suits):
    for suit in range(4):
        if ((suits >> (4 * suit)) & 15) >= 5:
            mask = 0
            for c in cards:
                if (c & 3) == suit:
                    mask |= RB[c]
            return FLUSH_VALUE[mask]
    return 0


def evaluate(cards):
    key = suits = 0
    for c in cards:
        key += RK[c]
        suits += SK[c]
    if (suits + FLUSH_ADD) & FLUSH_BITS:
        return _flush_value(cards, suits)
    return PLAIN[key]


TWO_PAIR = _code(2, [0, 0, 0])
PAIR_TENS = _code(1, [8, 12, 11, 10])
PAIR_SIXES = _code(1, [4, 12, 11, 10])


def strength(a, b, board):
    # made hand value, with draws on the flop and turn counted as a middling pair
    cards = [a, b] + board
    value = evaluate(cards)
    if len(board) >= 5 or value >= TWO_PAIR:
        return value
    suits = board_suits = 0
    mask = board_mask = 0
    for c in board:
        board_suits += SK[c]
        board_mask |= RB[c]
    suits = board_suits + SK[a] + SK[b]
    mask = board_mask | RB[a] | RB[b]
    flush_draw = any(((suits >> (4 * s)) & 15) == 4 and ((board_suits >> (4 * s)) & 15) < 4 for s in range(4))
    straight_draw = STRAIGHT_DRAW[mask] and not STRAIGHT_DRAW[board_mask]
    if flush_draw or straight_draw:
        if value >= PAIR_SIXES:
            return max(value, TWO_PAIR)
        return max(value, PAIR_TENS if flush_draw else PAIR_SIXES)
    return value


# ---------------------------------------------------------------- preflop classes

def hand_class(a, b):
    ra, rb = a >> 2, b >> 2
    if ra < rb:
        ra, rb = rb, ra
    if ra == rb or (a & 3) != (b & 3):
        return rb * 13 + ra  # pairs on the diagonal, offsuit below it
    return ra * 13 + rb  # suited above it


COMBOS = [(a, b) for a in range(52) for b in range(a + 1, 52)]
CLASS_COMBOS = [[] for _ in range(169)]
for _a, _b in COMBOS:
    CLASS_COMBOS[hand_class(_a, _b)].append((_a, _b))
CLASSES = [c for c in range(169) if CLASS_COMBOS[c]]

MAX_OPPONENTS_TABLE = 9
P_BUCKETS = (0.02, 0.04, 0.07, 0.10, 0.14, 0.19, 0.25, 0.32, 0.40, 0.50, 0.62, 0.76, 1.0)

# --- tables (written by bench/gen_tables.py) ---
EQV_DATA = (
    "498325326344346336381388416436469513545371544354368360358377409418453477515554374382560379378380"
    "395406440457493522565379398410609409395414425436476491542590387386420429624417430455456478503544"
    "576381401419431467672448469477487520560590403405425447462479694484505520546564584433434435444468"
    "493501728527534545569610446466460484485502517537752552566604631466489477504501526538552572774586"
    "599639505512508525532538561585598612810619650525538565544565580576604614615630831661584582595600"
    "597615631618649658660670844312194207222206200221226247255279311362239334221247222228220241261275"
    "293310362254263360253247249256241266277307326362256274278399265267256265272293324355372250274283"
    "310432284282289289304337348382249269283294318467303308310315325375391253259286300322335504323325"
    "348352369416270285283303325331363535365366376386419290299307299342336360399578394412421439309301"
    "318337338352381410414616419442447315341344356358357384408426431651449478352369366381375384392432"
    "449462476685475380393406421402423443451490485499505736223138146159154143160164168183200217259176"
    "237160175164154153174189193202219265194206253191184172174178194189220240279194198229290200198195"
    "196196206230239278182204226235325216210200210207225243266181198217226256341240235232228245258283"
    "187195216235257265386249261252264278294203215209238257270285397271275280300312211227216235257267"
    "296316444310318320334230231228249250272301310333491321338351244253252268268276304324337351537348"
    "376252270272290274294311333356373380590387292305316314310333329351376375391415634174114115128103"
    "110111123131133156179199150195126138129125118128136152163166208149165214151146139132137141150165"
    "176209160166193225165147159152150160171184211154167182194244163175170165161180199209142167174195"
    "206263189180186196187206219158157181194208220297202192205199215236155167176180194229226330235218"
    "227227238181181181185210227243252361248250265276183188199195195222238262280400271275283202199209"
    "208220233243258298309450295295206221224235233237249273299317318494323236250249265249254268281304"
    "310332350556154093094098086089089095109112125138166134168108111109089101103111119124149171126145"
    "174125115118108106113123135146173134149163177136123124116113128146151186136148161169201144141135"
    "130137142158168133140149162165225156151153148157168190135141148161180193248162168175173173194139"
    "140144155171192192260194188190185201146156152160170185214223295218211219237153161162172165186206"
    "223244334224233239166173174178183181202225259262381250260181188198202203210223234257264275420273"
    "214223217233212220246233267280288313500139074078086082068078084090094111118136113149096096088088"
    "078085086102106119143133125153111100096096085095100110119142135141148167118115107098089110110120"
    "155112132138154184124119111109116118133145114118134150157191128131123126126144151122120127140154"
    "169205137143137142139147125126127133154171178218169156160160166127128141144149166184201254179193"
    "182192134134146140150163177191219297196200213145149159153168168180198225234327217226161160164175"
    "178179179203229242253377246178189191197190196199203230253259280431126070072067070062065067074080"
    "087103114101137075082079078062069087084090109123115116135098096081082071086085090107131122130136"
    "153106093086082085087101111130104111131141152102102100092093102112113097119124130147170107112104"
    "107101114133107099116128139151184124122126118122139114110105126139148157197136138135147147119119"
    "121124134148163179219163171167165126126127127124148163177199243179180182133139130138142147168178"
    "201212285186192150143152145158160162184209199229335206160179179173170170188188208220228255387120"
    "064068066065048053062068072080086109095130073087076058056065062072077089102106114125085085075074"
    "063072072082091112108117125136092083089074076078082090107096107123124140096091094085081086097107"
    "091105122120137148107099093088095106111090098115121131141151108109111106102124106096102115122128"
    "135179134117122119127103110117110117134153151199143151147155106121114119119126140165178216152151"
    "160122124124119129134145159178192249167176138128137142132145152174178192207290189145156156163149"
    "157170170184196221226337120053058061052046048053059059069075091093117071074067059048054060060070"
    "077094098099123085078068065051060060072080100103112119123086079070065064065071087098096100106115"
    "129085085077066065078085097086099107122117140093086087079082089103089093097112124123146092099090"
    "095089106093091093101119128136154114113097106113101107101108114121139154163130129132130106104110"
    "112109115136147171202134145136110120114113112128132141167173212145153119121123124128129138143167"
    "171185265170136140136143144148144151176184192199297"
)
EQR_DATA = (
    "180149143150133121124118118134164203260178188156177147133118131123133157213263193190186182171147"
    "136125118131179215251188201223196182163158148122141173213267179181212218195182170151142146171214"
    "251154171201212219196178165150150161202260165156180191197215194175158153183207259162168161187189"
    "199204198172159199218244158162172170188192195208200171196217267170175175184177193204213208275208"
    "249283197212207218216217226238226240460278306239256248264251254250261257270311620360295309304305"
    "291290300294298322365404801246181184192178156161172204213223238271224260201203197172150179198213"
    "230247281218230254219199185181189199215224245286227242251258215213188193208230241250280211228238"
    "252269199198210210217229254270199211233244242262217218220223228254258196199219234245233276218228"
    "232236242260223224217229237247262358264266261278282236244244238258277269284436299298301315253267"
    "254255252268271303322514309324334256276262269264281277300329349598342358274274288290285291290315"
    "346353364704437298304314322311298307319349372402467806350230230238227212236231231248250259291281"
    "346257255239227231232237253251265278269294358270261255231245240256265267285279300310349271254262"
    "252252255270277294270286281310358281273274260261252282282256269292306313365279279280270248270280"
    "254269276299300316415286282290274289287281266279279302315334444309309302300304271285288283302302"
    "330348501316316321326294285294292293306323338359560328326360289290292302302288312339355343634335"
    "429313303311304315321315346356353357706499327324333330320327335345365401446532834403268266271262"
    "253259244267258260268304291398274279274252246263267265284293313306319407309289280269267259278282"
    "294307310329342400289290280274273283290281319295316312333415298294292285276287287304289287313330"
    "324408298308284277280298307288280305316330342456301308301296297317286301302309335328338500317321"
    "311317334293310300308319332342348536326326325374298310305328320317336347368587321334449309307319"
    "335324314335333357370642366506319331325317320338333345353373411719579329340348354342347366371405"
    "468538593846404275280279269258273269276274278293362320411295307276286261262279275284309378326324"
    "429317291303280280280278298310364327329348437307311291290276289290309377300309327340445324311292"
    "299294300309356302314321333354464327303301301285308363313308328346357354493322317322311308372296"
    "316308331341350379514325319318330404304320315324333334358360570331343347448314319323325328335347"
    "358372619336382500322323335326328337346362383390670432541334339341358358351354364391403459738597"
    "397400402413400401419428473520578614843431274282292284270274287278286300320389326430299306293291"
    "276276287287290318394327338441327311309293281292294296336389328341360462338324304300286301313335"
    "407317345342357481338326316311301317342397311321349349366499344315317314303347395326310329343369"
    "374532336323315324349432321326324327357367383542345324338349444323318318318335352362385594349359"
    "394507326315341334346350358357385638385423536338345340349354342362378395420687456579346366361372"
    "380360365394418461490752618421438426436430440444487529565594633857453301295303300294293304299304"
    "296340409331455313308308298292301302316317349417338346476337311307304293297315316353422340356365"
    "482330313302307300296316341431314338357368500343340322313300325351427338331352366367528345345329"
    "327320354453333322335348363377543341341349331364482317333356350359363378582357344345400501321334"
    "339342354364378391626366383418546345341339348344377377394401655401452574338346348363354362372383"
    "419451697481598380365378373382383398420444478504750642453440446466462477498521559596624650854454"
    "293301315306285295304312308320353443333463313314308309303300306318324348443338348482330322320310"
    "293305312330354454349354367499344334328315316323335373462326359367378529346341332336324342369468"
    "328333354370388557365347341340341379478334332340359380395572348349356358393502340333338346366382"
    "400598360375373412520348343349344371375385401643404403456566345350346358357365385401421673432481"
    "583377369362374380379390422441463708510619375384392396410414426451476508530752649468473476498486"
    "501518557597611621669856466297303314295298301296302318343384471339495318326323310301310318326350"
    "381473343357494350335318321304314331345377472356362385508344344335324318333357396487341343374367"
    "539359338330332340362404482325345358377378578357344350348367413499331349365379382408592362363375"
    "390425528330336344353390374391626376381409458554336354359367376380402418646419433496593355354376"
    "376366396390408446699459514609369375385384398396423447466487732524610393424425431420451456495515"
    "543546773656501486504507515539557580597621644663847474306297323310299303311314336349417495350511"
    "325333318309305311317330368423499340360522351346331320307338350367429515351366383532358352351330"
    "328355385432505343371376387551359354360346346380440514338359372383381575377357356372395469537342"
    "335360367389401607367376395431483540351347353364384396402645395409441495574357367353371374386405"
    "429672441469537594379370378400380414418446460705476538610394393402408423428462471498502735564631"
    "433450442467468483496538557582575802661512522525541552565570588607625650662854485310316320308304"
    "304309331358395445505347508341348330320310332336365402450525357360529356341347320335353372406463"
    "523345378385541359349338348347372421479545343360389394577372354355374380425483534347348369386409"
    "591373376377412441497546354349369386385408620398422418465502568346364361372397415430659415445480"
    "524578372385383375402412446462690466522541605381401400405425436449480499724526562626426436434449"
    "457471497516530549761590633472488485506504526536576580590614801650534551552544565573577607617638"
    "652672850489307315333318308320326372389420476516349530336352323337324344375402434475526350375538"
    "360349343341352387403454484531364380396562380367353360388431457500543339376368398581368375379404"
    "430463513548346354367396421620390410414445477516559367371373396409444650434446481496530580376382"
    "373410419444467675471485514561599398409413406436444460481715511546573615418435439454452469493515"
    "529740558584629452463469483495500517537569582783596625503519518532526550550588596611616824656548"
    "550560567573599594617635652670674843501327332347331355366378414456479512552356529342362368363384"
    "386426452484519552373384570372381392393418435460494526565385400409596400414402434433470485527578"
    "377398410431625430428457455479506548582379397417440456664447474476494522550580394403436433463479"
    "694497496508530553596434434430458469481506727508527551582605451462465474481511523555755561578591"
    "619473493499507513519552554571768578607646484511521534533538552566583590799618639534531547564581"
    "577581596617620630830664572581591599602606617618650645657680848"
)
# --- end tables ---

# Equilibrium first-in shove chart (from Logan's solver): shove probability x255 for
# [players behind 1..21][stack in big blinds on PUSH_GRID][hand class].
PUSH_GRID = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0, 9.5, 10.0, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 22, 24, 26, 28, 30]
PUSH_DATA = (
    "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"
)


def _unpack(data, rows):
    if not data:
        return None
    values = [int(data[i:i + 3]) / 1000 for i in range(0, len(data), 3)]
    return [values[r * 169:(r + 1) * 169] for r in range(rows)]


def build_order(eqv):
    # hands ranked the way a sensible player ranks them: heads-up value plus multiway value
    score = {c: 2 * eqv[0][c] + eqv[2][c] for c in CLASSES}
    order = sorted(CLASSES, key=lambda c: (-score[c], c))
    combo_order, class_pct, start = [], [0.0] * 169, 0
    for c in order:
        combo_order.extend(CLASS_COMBOS[c])
        size = len(CLASS_COMBOS[c])
        class_pct[c] = (start + size / 2) / 1326
        start += size
    return order, combo_order, class_pct


EQV = _unpack(EQV_DATA, MAX_OPPONENTS_TABLE)  # EQV[n-1][class]: share vs n random hands
EQR = _unpack(EQR_DATA, len(P_BUCKETS))  # EQR[bucket][class]: share vs the top P_BUCKETS[bucket] of hands
if EQV:
    ORDER, COMBO_ORDER, CLASS_PCT = build_order(EQV)


PUSH = zlib.decompress(base64.b64decode(PUSH_DATA))
PUSH_BEHIND = len(PUSH) // (len(PUSH_GRID) * 169)
CLASS_SIZE = [len(CLASS_COMBOS[c]) for c in range(169)]


def _push_row(behind, stack_bb):
    # (row offset low, row offset high, blend) for interpolating between stack grid points
    k = min(max(behind, 1), PUSH_BEHIND) - 1
    grid, ng = PUSH_GRID, len(PUSH_GRID)
    if stack_bb <= grid[0]:
        lo = hi = 0
        t = 0.0
    elif stack_bb >= grid[-1]:
        lo = hi = ng - 1
        t = 0.0
    else:
        hi = next(i for i, g in enumerate(grid) if g >= stack_bb)
        lo = hi - 1
        t = (stack_bb - grid[lo]) / (grid[hi] - grid[lo])
    base = k * ng * 169
    return base + lo * 169, base + hi * 169, t


def shove_prob(behind, stack_bb, h):
    lo, hi, t = _push_row(behind, stack_bb)
    return ((1 - t) * PUSH[lo + h] + t * PUSH[hi + h]) / 255.0


def shove_share(behind, stack_bb):
    # share of all starting hands an equilibrium player shoves first in
    lo, hi, t = _push_row(behind, stack_bb)
    total = 0.0
    for c in CLASSES:
        total += ((1 - t) * PUSH[lo + c] + t * PUSH[hi + c]) * CLASS_SIZE[c]
    return total / (255.0 * 1326)


def data_weight(n):
    # how far observations may pull us off the equilibrium baseline
    return 0.85 * n / (n + 4.0)


def eq_vs_top(h, p):
    if p >= 1.0:
        return EQV[0][h]
    if p <= P_BUCKETS[0]:
        return EQR[0][h]
    for i in range(1, len(P_BUCKETS)):
        if p <= P_BUCKETS[i]:
            lo, hi = P_BUCKETS[i - 1], P_BUCKETS[i]
            t = (p - lo) / (hi - lo)
            return EQR[i - 1][h] * (1 - t) + EQR[i][h] * t
    return EQV[0][h]


def eq_heads_up(h, p, w):
    return w * EQV[0][h] + (1 - w) * eq_vs_top(h, p)


def multiway_factor(h, n):
    # beating several hands is not independent; random-hand tables say by how much
    if n <= 1:
        return 1.0
    base = EQV[0][h]
    if n <= MAX_OPPONENTS_TABLE:
        target = EQV[n - 1][h]
    else:
        last, prev = EQV[MAX_OPPONENTS_TABLE - 1][h], EQV[MAX_OPPONENTS_TABLE - 2][h]
        target = last * (last / prev) ** (n - MAX_OPPONENTS_TABLE) if prev else last
    return min(3.0, max(0.7, target / max(base ** n, 1e-9)))


def eq_multi(h, ranges):
    if not ranges:
        return 1.0
    e = 1.0
    for p, w in ranges:
        e *= eq_heads_up(h, p, w)
    return min(1.0, e * multiway_factor(h, len(ranges)))


# ---------------------------------------------------------------- opponent model

PRIOR_N = 4.0
PRIORS = {
    "pf0": (0.55, 0.25, 0.20),  # fold, call, raise with no raise yet
    "pf1": (0.65, 0.25, 0.10),  # facing one raise
    "pf2": (0.72, 0.20, 0.08),  # facing a reraise
    "commit": (0.70, 0.30),  # fold, continue when the call is most of the stack
    "open": (0.60, 0.40),  # after the flop with nothing to call: check, bet
    "face": (0.45, 0.40, 0.15),  # after the flop facing a bet: fold, call, raise
    "face2": (0.30, 0.50, 0.20),  # after the flop facing a raise
    "jam": (0.70, 0.30),  # first in with at most SHORT_BB: anything else, all-in
}
SHORT_BB = 30  # the shove chart covers stacks up to here
PUSH_FOLD_BB = 14  # first in at or below this effective stack, our baseline is the shove chart
RISK_PREMIUM = 0.1  # share of chips at risk an early all-in must win by
# how much of its range a sound player opens first in, by seats left to act
OPEN_FRACTION = {1: 0.50, 2: 0.42, 3: 0.28, 4: 0.22, 5: 0.18, 6: 0.15, 7: 0.13, 8: 0.11}
W_GRID = [i / 10 for i in range(11)]
W_PRIOR = [0.05, 0.10, 0.14, 0.14, 0.12, 0.10, 0.09, 0.08, 0.07, 0.06, 0.05]
DECAY = 0.98  # per finished hand, so a seat that changes gears is re-read within a few dozen hands


def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


class Opponent:
    def __init__(self):
        self.counts = {k: [0.0] * len(v) for k, v in PRIORS.items()}
        self.w_post = list(W_PRIOR)
        self.showdowns = 0.0

    def freq(self, key):
        c, prior = self.counts[key], PRIORS[key]
        total = sum(c) + PRIOR_N
        return [(c[i] + PRIOR_N * prior[i]) / total for i in range(len(c))]

    def seen(self, key):
        return sum(self.counts[key])

    def decay(self):
        for v in self.counts.values():
            for i in range(len(v)):
                v[i] *= DECAY
        self.showdowns *= DECAY

    def randomness(self):
        # how much of its play ignores its cards: 0 plays a tight ranked range, 1 plays any two
        r0, r1, r2 = self.freq("pf0")[2], self.freq("pf1")[2], self.freq("pf2")[2]
        deep = self.seen("pf1") + self.seen("pf2")
        # a ranged player raises far less often into raises; a random one raises just as often
        shape = clamp(((r1 + r2) / 2 / max(r0, 0.05) - 0.35) / 0.55, 0.0, 1.0)
        loose_calls = clamp((self.freq("commit")[1] - 0.5) / 0.35, 0.0, 1.0)
        shape = max(shape, loose_calls * min(1.0, self.seen("commit") / 6))
        shape_conf = deep / (deep + 8.0)
        structural = (1 - shape_conf) * 0.1 + shape_conf * shape
        total = sum(self.w_post)
        posterior = sum(w * p for w, p in zip(W_GRID, self.w_post)) / total
        sd_conf = self.showdowns / (self.showdowns + 3.0)
        return clamp(sd_conf * posterior + (1 - sd_conf) * structural, 0.03, 0.97)

    def saw_showdown(self, pct, p):
        # pct is where the shown hand sits in the ranking, p the range its actions implied
        inside = pct <= p + 0.03
        for i, w in enumerate(W_GRID):
            like = w + (1 - w) * ((1 / max(p, 0.02)) if inside else 0.04)
            self.w_post[i] = self.w_post[i] * like
        total = sum(self.w_post)
        self.w_post = [0.97 * v / total + 0.03 * pr for v, pr in zip(self.w_post, W_PRIOR)]
        self.showdowns += 1


def decision_kind(street, action, owed, remaining, raises):
    if owed > 0 and owed >= 0.45 * remaining:
        return "commit"
    if street == "preflop":
        if owed == 0:
            return "pf0" if action in ("bet", "raise") else None  # big blind option
        return "pf%d" % min(raises, 2)
    if owed == 0:
        return "open"
    return "face" if raises <= 1 else "face2"


def replay(history, start, n):
    # every voluntary action with the situation it was taken in:
    # (seat, street, action, kind, raises before it, all-in?, stack in big blinds, seats left to act preflop)
    stack, bets, bet, street, raises = list(start), [0] * n, 0, None, 0
    out = []
    bb_seat, bb = None, 1
    acted = set()
    gone = {i for i in range(n) if start[i] <= 0}
    for e in history:
        s, action, to, st = e["seat"], e["action"], e["to"], e["street"]
        if st != street:
            street, bets, bet, raises = st, [0] * n, 0, 0
        if action == "blind":
            stack[s] -= to - bets[s]
            bets[s] = to
            bet = max(bet, to)
            bb_seat, bb = s, max(bb, to)
            continue
        owed = max(0, bet - bets[s])
        kind = decision_kind(st, action, owed, stack[s], raises)
        all_in = action in ("bet", "raise", "call") and to - bets[s] >= stack[s]
        depth = (stack[s] + bets[s]) / bb
        behind = 0
        if st == "preflop" and bb_seat is not None:
            first = (bb_seat + 1) % n
            mine = (s - first) % n
            behind = sum(1 for j in range(n) if j != s and j not in gone and j not in acted and (j - first) % n > mine)
            acted.add(s)
        out.append((s, st, action, kind, raises, all_in, depth, behind))
        if action == "fold":
            gone.add(s)
        if action in ("call", "bet", "raise"):
            stack[s] -= to - bets[s]
            bets[s] = to
            if action != "call" and to > bet:
                bet = to
                raises += 1
    return out


def invested(history, n):
    last = {}
    for e in history:
        last[(e["seat"], e["street"])] = e["to"]
    totals = [0] * n
    for (seat, _), to in last.items():
        if 0 <= seat < n:
            totals[seat] += to
    return totals


ACTION_INDEX = {
    "commit": {"fold": 0, "call": 1, "raise": 1, "bet": 1},
    "open": {"check": 0, "bet": 1, "raise": 1},
}
TRIPLE_INDEX = {"fold": 0, "check": 1, "call": 1, "bet": 2, "raise": 2}
BOARD_LEN = {"flop": 3, "turn": 4, "river": 5}


# ---------------------------------------------------------------- game view

class View:
    def __init__(self, info):
        self.me = int(info["seat"])
        self.stacks = [int(s) for s in info["stacks"]]
        self.n = len(self.stacks)
        self.hole = [card_id(c) for c in info["hole_cards"]]
        self.board = [card_id(c) for c in info["board"]]
        self.street = info["street"]
        self.pot = int(info["pot"])
        self.bets = [int(b) for b in info["street_bet"]]
        self.bet = int(info["current_bet"])
        self.my_bet = int(info["street_bet_self"])
        self.to_call = int(info["to_call"])
        self.min_to = int(info["min_raise_to"])
        self.max_to = int(info["max_raise_to"])
        self.legal = list(info["legal_actions"])
        self.folded = list(info["folded"])
        self.button = int(info["button"])
        self.bb = int(info["blinds"][1])
        self.history = info["history"]
        self.live = [j for j in range(self.n) if j != self.me and not self.folded[j]]
        self.responders = [j for j in self.live if self.stacks[j] > 0]
        self.all_in = [j for j in self.live if self.stacks[j] == 0]
        self.spent = invested(self.history, self.n)
        self.start = [self.stacks[i] + self.spent[i] for i in range(self.n)]
        self.decisions = replay(self.history, self.start, self.n)
        self.raises = sum(1 for d in self.decisions if d[1] == self.street and d[2] in ("bet", "raise"))

    def max_total(self, j):
        return self.bets[j] + self.stacks[j]

    def winnable(self, mine, adds):
        # the pot we can actually take if we put `mine` more in and seats add `adds`:
        # nobody's chips above our own total are ours to win
        cap = self.spent[self.me] + mine
        total = 0
        for i in range(self.n):
            chips = self.spent[i] + (mine if i == self.me else adds.get(i, 0))
            total += min(chips, cap)
        return total

    def seat_order(self, j):
        return (j - self.button - 1) % self.n

    def in_position(self, group):
        mine = self.seat_order(self.me)
        return all(mine > self.seat_order(j) for j in group)


def fallback(info):
    legal = info.get("legal_actions") or []
    return {"action": "check", "amount": 0} if "check" in legal else {"action": "fold", "amount": 0}


# ---------------------------------------------------------------- agent

class Agent:
    def __init__(self):
        self.opps = {}
        self.rng = random.Random()
        self.pending = None  # (signature, history, start) of the hand we are in

    # ---- bookkeeping

    def opp(self, seat):
        if seat not in self.opps:
            self.opps[seat] = Opponent()
        return self.opps[seat]

    @staticmethod
    def signature(history):
        return tuple((e["seat"], e["to"]) for e in history if e["action"] == "blind")

    def track(self, view):
        sig = self.signature(view.history)
        if self.pending and self.pending[0] != sig:
            self.learn(self.pending[1], self.pending[2], None, view.me)
        self.pending = (sig, view.history, view.start)
        self.me = view.me

    def hand_over(self, result):
        try:
            history = result["history"]
            stacks = [int(s) for s in result["stacks"]]
            n = len(stacks)
            won = {int(k): int(v) for k, v in result.get("won", {}).items()}
            spent = invested(history, n)
            start = [stacks[i] - won.get(i, 0) + spent[i] for i in range(n)]
            shown = {int(k): v for k, v in (result.get("shown") or {}).items()}
            me = getattr(self, "me", None)
            if self.pending and self.pending[0] != self.signature(history):
                self.learn(self.pending[1], self.pending[2], None, me)
            self.pending = None
            self.learn(history, start, shown, me)
        except Exception:
            pass

    def learn(self, history, start, shown, me):
        if not TUNE["learn"]:
            return
        n = len(start)
        decisions = replay(history, start, n)
        ranges = {}
        for act in decisions:
            seat, street, action, kind, raises, all_in, depth, _ = act
            if seat == me or kind is None:
                continue
            o = self.opp(seat)
            if street == "preflop":
                ranges[seat] = ranges.get(seat, 1.0) * self.act_share(o, act)
                if raises == 0 and depth <= SHORT_BB:
                    o.counts["jam"][1 if (action == "raise" and all_in) else 0] += 1
            if kind in ACTION_INDEX:
                o.counts[kind][ACTION_INDEX[kind].get(action, 0)] += 1
            else:
                o.counts[kind][TRIPLE_INDEX.get(action, 0)] += 1
        for seat, cards in (shown or {}).items():
            if seat == me or seat not in ranges:
                continue
            try:
                a, b = card_id(cards[0]), card_id(cards[1])
            except (KeyError, IndexError, TypeError):
                continue
            self.opp(seat).saw_showdown(CLASS_PCT[hand_class(a, b)], max(ranges[seat], 0.015))
        for o in self.opps.values():
            o.decay()

    @staticmethod
    def continue_share(o, kind, action):
        f = o.freq(kind)
        if kind == "commit":
            return f[1]
        if kind == "open":
            return f[1] if action in ("bet", "raise") else 1.0
        if action in ("bet", "raise"):
            return f[2]
        if action in ("call", "check"):
            return f[1] + f[2]
        return 1.0

    def act_share(self, o, act):
        # share of all hands that would have taken this preflop action
        _, _, action, kind, raises, all_in, depth, behind = act
        if action == "raise" and all_in and raises == 0 and depth <= SHORT_BB:
            # a short first-in shove: start from the equilibrium range, move toward what this seat shows
            w = data_weight(o.seen("jam"))
            return (1 - w) * shove_share(behind, depth) + w * o.freq("jam")[1]
        if action == "raise" and raises == 0 and kind == "pf0":
            w = data_weight(o.seen("pf0"))
            base = OPEN_FRACTION.get(behind, 0.10) if behind else 0.5
            return (1 - w) * base + w * o.freq("pf0")[2]
        return self.continue_share(o, kind, action)

    def preflop_range(self, view, seat):
        p = 1.0
        o = self.opp(seat)
        for act in view.decisions:
            if act[0] == seat and act[1] == "preflop" and act[3] is not None:
                p *= self.act_share(o, act)
        return max(p, 0.015)

    def postflop_filters(self, view, seat):
        o = self.opp(seat)
        filters = []
        for s, street, action, kind, *_ in view.decisions:
            if s != seat or street == "preflop" or kind is None:
                continue
            f = o.freq(kind)
            if kind == "open":
                filters.append((BOARD_LEN[street], "top" if action in ("bet", "raise") else "check", f[1]))
            elif kind in ("face", "face2"):
                share = f[2] if action == "raise" else f[1] + f[2]
                filters.append((BOARD_LEN[street], "top", share))
            elif kind == "commit":
                filters.append((BOARD_LEN[street], "top", f[1]))
        return filters

    # ---- decide

    def decide(self, info):
        started = time.perf_counter()
        try:
            limit = float(info.get("time_limit") or 10.0)
            if limit >= 1.0:
                budget = min(0.8, 0.12 * limit)
            elif limit >= 0.1:
                budget = 0.3 * limit
            else:
                budget = max(0.0002, 0.36 * limit - 0.0006)
            deadline = started + budget
            view = View(info)
            self.track(view)
            if not view.legal:
                return fallback(info)
            if view.street == "preflop" or EQV is None:
                choice = self.preflop(view)
            else:
                choice = self.postflop(view, deadline, budget)
            return self.legalize(view, choice)
        except Exception:
            return fallback(info)

    def legalize(self, view, choice):
        action, amount = choice
        if action in ("bet", "raise"):
            word = "raise" if "raise" in view.legal else "bet" if "bet" in view.legal else None
            if word is None:
                action = "call" if "call" in view.legal else "check"
            else:
                return {"action": word, "amount": int(clamp(int(amount), view.min_to, view.max_to))}
        if action == "check" and "check" not in view.legal:
            action = "fold"
        if action == "call" and "call" not in view.legal:
            action = "check" if "check" in view.legal else "fold"
        if action == "fold" and "check" in view.legal:
            action = "check"
        return {"action": action, "amount": 0}

    def raise_sizes(self, view, sizes):
        if not view.responders or ("bet" not in view.legal and "raise" not in view.legal):
            return []
        out = []
        for x in sizes:
            x = int(clamp(int(x), view.min_to, view.max_to))
            if x >= 0.6 * view.max_to:
                x = view.max_to
            if x > view.bet and x not in out:
                out.append(x)
        if view.max_to > view.bet and view.max_to not in out:
            out.append(view.max_to)
        return out

    # ---- preflop

    def facing(self, view, j, x):
        # fold, call, reraise chances for seat j if we make it x to go
        o = self.opp(j)
        owed = x - view.bets[j]
        if owed <= 0:
            return 0.0, 1.0, 0.0
        if owed >= 0.45 * view.stacks[j] or (x >= view.max_to and owed >= 0.25 * view.stacks[j]):
            cont = o.freq("commit")[1]
            return 1 - cont, cont, 0.0
        f, c, r = o.freq("pf%d" % min(view.raises + 1, 2))
        if x >= view.max_to:
            c, r = c + r, 0.0
        return f, c, r

    def realization(self, view, group, all_in):
        if all_in:
            return 1.0
        r = 0.96 if view.in_position(group) else 0.86
        return r - 0.05 * (len(group) - 1)

    def utility(self, view, gain):
        # concave in the stack we end the hand with, scaled to the stack we started it with
        alpha = TUNE["alpha"]
        scale = max(1, view.start[view.me])
        behind = view.stacks[view.me]
        after = max(0.0, behind + gain)
        if alpha == 1:
            return gain
        return scale * ((after / scale) ** alpha - (behind / scale) ** alpha) / alpha

    def gamble(self, view, win, pot, mine):
        # utility of putting `mine` more chips in and taking down `pot` with probability `win`
        return win * self.utility(view, pot - mine) + (1 - win) * self.utility(view, -mine)

    def showdown_ev(self, view, h, x, fixed, maybes, ranges):
        # value relative to folding, when we end up x in on this street;
        # fixed seats are certainly in, maybes are (probability, seat) pairs
        maybes = sorted(maybes, key=lambda m: -m[0])[:5]
        total = 0.0
        for mask in range(1 << len(maybes)):
            prob, group = 1.0, list(fixed)
            for i, (pr, j) in enumerate(maybes):
                if mask >> i & 1:
                    prob *= pr
                    group.append(j)
                else:
                    prob *= 1 - pr
            if prob <= 1e-6:
                continue
            if not group:
                total += prob * self.utility(view, view.pot)
                continue
            cover = max(view.max_total(j) for j in group)
            mine = min(x, cover) - view.my_bet
            adds = {j: max(0, min(x, view.max_total(j)) - view.bets[j]) for j in group}
            e = eq_multi(h, [ranges[j] for j in group])
            all_in = x >= view.max_to or all(view.max_total(j) <= x for j in group)
            r = self.realization(view, group, all_in)
            total += prob * self.gamble(view, r * e, view.winnable(mine, adds), mine)
        return total

    def preflop(self, view):
        h = hand_class(*view.hole)
        ranges = {j: (self.preflop_range(view, j), self.opp(j).randomness()) for j in view.live}
        options = []
        if "fold" in view.legal and view.to_call > 0:
            options.append((0.0, ("fold", 0)))

        # call or check: seats that still owe chips come along with their continue chance
        x = min(view.bet, view.max_to)
        fixed, maybes, ranges_call = [], [], dict(ranges)
        for j in view.live:
            if view.bets[j] >= view.bet or view.stacks[j] == 0:
                fixed.append(j)
            else:
                f, c, r = self.facing_call(view, j)
                p, w = ranges[j]
                ranges_call[j] = (max(p * (c + r), 0.015), w)
                maybes.append((c + r, j))
        word = "call" if "call" in view.legal else "check"
        call_in = x - view.my_bet
        call_ev = self.showdown_ev(view, h, x, fixed, maybes, ranges_call)
        if call_in >= 0.45 * view.stacks[view.me]:
            call_ev -= self.risk_premium(view, call_in)
        options.append((call_ev, (word, 0)))

        # raises
        bb = view.bb
        if view.raises == 0:
            limpers = sum(1 for d in view.decisions if d[1] == "preflop" and d[2] == "call")
            sizes = [view.bet + (1.5 + limpers) * bb]
        elif view.raises == 1:
            sizes = [view.bet * (3 if view.in_position(view.live) else 3.5)]
        else:
            sizes = [view.bet * 2.3]
        passive = max(options, key=lambda o: o[0])
        shove_ev = None
        for x in self.raise_sizes(view, sizes):
            ev = self.raise_ev(view, h, x, ranges)
            if x == view.max_to:
                ev -= self.risk_premium(view, x - view.my_bet)
            options.append((ev, ("raise", x)))
            if x == view.max_to:
                shove_ev = ev
        best = max(options, key=lambda o: o[0])

        eff = min(view.max_to, max(view.max_total(j) for j in view.live)) / bb
        if view.raises == 0 and shove_ev is not None and eff <= PUSH_FOLD_BB:
            # equilibrium shove chart, pulled toward our exploit read as we learn how the callers call
            p = shove_prob(len(view.responders), eff, h)
            seen = sum(self.opp(j).seen("commit") for j in view.responders) / len(view.responders)
            w = data_weight(seen)
            p = (1 - w) * p + w * (1.0 if shove_ev > passive[0] else 0.0)
            return ("raise", view.max_to) if self.rng.random() < p else passive[1]
        return best[1]

    @staticmethod
    def risk_premium(view, risked):
        # Our read of who calls and with what is an estimate; while blinds are small next to our
        # stack a better spot will come, so an all-in has to clear that estimate's error. Fades
        # to nothing as the blinds catch up.
        m = (view.stacks[view.me] + view.my_bet) / max(1, 1.5 * view.bb)
        return RISK_PREMIUM * min(1.0, m / 40.0) * risked

    def facing_call(self, view, j):
        # a seat that still owes chips after we just call
        o = self.opp(j)
        owed = view.bet - view.bets[j]
        if owed >= 0.45 * view.stacks[j]:
            cont = o.freq("commit")[1]
            return 1 - cont, cont, 0.0
        return o.freq("pf%d" % min(view.raises, 2))

    def raise_ev(self, view, h, x, ranges):
        fixed = list(view.all_in)
        maybes, rr, rr_seat, no_rr = [], 0.0, None, 1.0
        rng = dict(ranges)
        for j in view.responders:
            f, c, r = self.facing(view, j, x)
            p, w = ranges[j]
            rng[j] = (max(p * (c + r), 0.015), w)
            no_rr *= 1 - r
            if r > rr:
                rr, rr_seat = r, j
            maybes.append((c / max(1e-9, 1 - r), j))
        ev = self.showdown_ev(view, h, x, fixed, maybes, rng)
        if rr_seat is None or no_rr >= 0.999:
            return ev
        # someone comes over the top: assume a shove and pick the better of calling and folding
        j = rr_seat
        p, w = ranges[j]
        t = min(view.max_total(j), view.max_to)
        mine = t - view.my_bet
        e = eq_multi(h, [(max(p * rr, 0.015), w)] + [ranges[k] for k in fixed])
        call_shove = self.gamble(view, e, view.winnable(mine, {j: t - view.bets[j]}), mine)
        ev_rr = max(self.utility(view, -(x - view.my_bet)), call_shove)
        return no_rr * ev + (1 - no_rr) * ev_rr

    # ---- after the flop

    def build_pool(self, view, seat, size):
        p = self.preflop_range(view, seat)
        w = self.opp(seat).randomness()
        dead = set(view.hole) | set(view.board)
        top = max(1, int(p * 1326 + 0.5))
        rnd, cands, tries = self.rng.random, [], 0
        while len(cands) < size and tries < 8 * size:
            tries += 1
            if rnd() < w:
                a, b = COMBOS[int(rnd() * 1326)]
                tag = True
            else:
                a, b = COMBO_ORDER[int(rnd() * top)]
                tag = False
            if a in dead or b in dead:
                continue
            cands.append((a, b, tag))
        for board_len, kind, share in self.postflop_filters(view, seat):
            board = view.board[:board_len]
            ranked = sorted((c for c in cands if not c[2]), key=lambda c: -strength(c[0], c[1], board))
            if kind == "top":
                kept = ranked[:max(1, int(len(ranked) * share + 0.5))] if ranked else []
                survive = share
            else:
                kept = ranked[int(len(ranked) * share * 0.5):]
                survive = 1 - share * 0.5
            kept += [c for c in cands if c[2] and rnd() < survive]
            if kept:
                cands = kept
        if not cands:
            return [(a, b, 0.5) for a, b in COMBOS if a not in dead and b not in dead]
        ranked = sorted(cands, key=lambda c: -strength(c[0], c[1], view.board))
        size = len(ranked)
        return [(a, b, i / size) for i, (a, b, _) in enumerate(ranked)]

    def simulate(self, view, pools, deadline, limit=6000):
        hole, board = view.hole, view.board
        need = 5 - len(board)
        dead = set(hole) | set(board)
        deck = [c for c in range(52) if c not in dead]
        nd = len(deck)
        bk = sum(RK[c] for c in board)
        bs = sum(SK[c] for c in board)
        rnd, clock = self.rng.random, time.perf_counter
        h0, h1 = hole
        out = []
        while len(out) < limit:
            if (len(out) & 7) == 0 and clock() > deadline:
                break
            used = set()
            hands = []
            for pool in pools:
                np_ = len(pool)
                for _ in range(10):
                    a, b, pct = pool[int(rnd() * np_)]
                    if a not in used and b not in used:
                        break
                else:
                    while True:
                        a, b = deck[int(rnd() * nd)], deck[int(rnd() * nd)]
                        if a != b and a not in used and b not in used:
                            break
                    pct = 0.5
                used.add(a)
                used.add(b)
                hands.append((a, b, pct))
            run = []
            while len(run) < need:
                c = deck[int(rnd() * nd)]
                if c not in used and c not in run:
                    run.append(c)
            k0, s0 = bk, bs
            for c in run:
                k0 += RK[c]
                s0 += SK[c]
            full = board + run
            k, s = k0 + RK[h0] + RK[h1], s0 + SK[h0] + SK[h1]
            mine = _flush_value(full + [h0, h1], s) if (s + FLUSH_ADD) & FLUSH_BITS else PLAIN[k]
            vals = []
            for a, b, _ in hands:
                k, s = k0 + RK[a] + RK[b], s0 + SK[a] + SK[b]
                vals.append(_flush_value(full + [a, b], s) if (s + FLUSH_ADD) & FLUSH_BITS else PLAIN[k])
            out.append((mine, vals, [hd[2] for hd in hands], [rnd() for _ in hands]))
        return out

    def postflop(self, view, deadline, budget):
        h = hand_class(*view.hole)
        river = len(view.board) == 5
        started = deadline - budget
        if budget < 0.0015:
            return self.quick_postflop(view)
        base = 40 if budget < 0.01 else 90 if budget < 0.1 else 160
        pool_size = max(12, int(base * 2 / (len(view.live) + 1)))
        pools = [self.build_pool(view, j, pool_size) for j in view.live]
        # sampling gets about half the budget; scoring the bet sizes gets the rest
        samples = self.simulate(view, pools, started + 0.55 * budget)
        hard = started + 1.5 * budget
        if len(samples) < 12:
            return self.quick_postflop(view)

        idx = {j: i for i, j in enumerate(view.live)}
        resp = [idx[j] for j in view.responders]
        fixed = [idx[j] for j in view.all_in]
        weights = [self.opp(j).randomness() for j in view.live]
        n = len(samples)

        def share(mine, vals, group):
            best, ties = 0, 0
            for i in group:
                v = vals[i]
                if v > best:
                    best, ties = v, 1
                elif v == best:
                    ties += 1
            if mine > best:
                return 1.0
            if mine == best:
                return 1.0 / (ties + 1)
            return 0.0

        everyone = list(range(len(view.live)))
        shares = [share(m, v, everyone) for m, v, _, _ in samples]
        base_r = 1.0 if river else (0.96 if view.in_position(view.live) else 0.88)
        u = self.utility
        options = []
        if view.to_call > 0:
            options.append((0.0, ("fold", 0)))
            mine = min(view.bet, view.max_to) - view.my_bet
            r = 1.0 if mine >= view.stacks[view.me] else base_r
            pot = view.winnable(mine, {})
            options.append((sum(u(view, r * s * pot - mine) for s in shares) / n, ("call", 0)))
        else:
            options.append((sum(u(view, base_r * s * view.pot) for s in shares) / n, ("check", 0)))
        passive = max(options, key=lambda o: o[0])
        if river and evaluate(view.hole + view.board) == evaluate(view.board):
            return passive[1]  # the board plays: nothing better can fold to us

        if view.to_call > 0:
            sizes = [view.bet * 3]
        else:
            sizes = [view.pot * 0.5, view.pot * 0.8, view.pot * 1.2]
        for x in self.raise_sizes(view, sizes):
            if time.perf_counter() > hard:
                break
            conts = [self.post_continue(view, view.live[i], x) for i in range(len(view.live))]
            total = squared = 0.0
            for mine_v, vals, pcts, us in samples:
                group = list(fixed)
                for i in resp:
                    roll, w, cont = us[i], weights[i], conts[i]
                    if (roll / w < cont) if roll < w else (pcts[i] <= cont):
                        group.append(i)
                if not group:
                    value = u(view, view.pot)
                    total += value
                    squared += value * value
                    continue
                seats = [view.live[i] for i in group]
                cover = max(view.max_total(j) for j in seats)
                mine = min(x, cover) - view.my_bet
                adds = {j: max(0, min(x, view.max_total(j)) - view.bets[j]) for j in seats}
                all_in = x >= view.max_to or all(view.max_total(j) <= x for j in seats)
                r = 1.0 if (all_in or river) else base_r
                value = u(view, r * share(mine_v, vals, group) * view.winnable(mine, adds) - mine)
                total += value
                squared += value * value
            # score by a pessimistic estimate so a size that only sampled lucky doesn't win
            mean = total / n
            error = (max(0.0, squared / n - mean * mean) / n) ** 0.5
            options.append((mean - 0.65 * error, ("raise", x)))
        best = max(options, key=lambda o: o[0])
        margin = max(0.18 * view.bb, 0.025 * view.pot)
        if best[1][0] == "raise" and best[0] < passive[0] + margin:
            return passive[1]
        return best[1]

    def post_continue(self, view, j, x):
        o = self.opp(j)
        owed = x - view.bets[j]
        if owed <= 0:
            return 1.0
        reraised = o.freq("face2")
        if owed >= 0.45 * view.stacks[j]:
            # a seat that already bet this street is calling off with its betting range, not its average hand
            if view.bets[j] > 0:
                return max(o.freq("commit")[1], reraised[1] + reraised[2])
            return o.freq("commit")[1]
        f = o.freq("face") if view.raises == 0 else reraised
        cont = f[1] + f[2]
        ratio = (owed / max(1, view.pot)) / 0.6
        return clamp(cont ** (ratio ** 0.5), 0.02, 1.0)

    def quick_postflop(self, view):
        # no time for runouts: rank our hand (draws counted) against each opponent's modeled range
        # on this board, narrowed by how it acted this street, then play by thresholds
        board, rnd = view.board, self.rng.random
        dead = set(view.hole) | set(board)
        mine = strength(view.hole[0], view.hole[1], board)
        tries = max(12, 48 // max(1, len(view.live)))
        eq = 1.0
        for j in view.live:
            o = self.opp(j)
            p, w = self.preflop_range(view, j), o.randomness()
            top = max(1, int(p * 1326))
            vals = []
            for _ in range(tries):
                a, b = COMBOS[int(rnd() * 1326)] if rnd() < w else COMBO_ORDER[int(rnd() * top)]
                if a not in dead and b not in dead:
                    vals.append(strength(a, b, board))
            if not vals:
                continue
            aggressive = [d for d in view.decisions if d[0] == j and d[1] == view.street and d[2] in ("bet", "raise")]
            if aggressive:
                kind = aggressive[-1][3]
                f = o.freq(kind)
                share = f[1] if kind in ("open", "commit") else f[2]
                share = w + (1 - w) * max(0.2, share)
                vals.sort(reverse=True)
                vals = vals[:max(1, int(len(vals) * share + 0.5))]
            beat = sum(1.0 if mine > v else 0.5 if mine == v else 0.0 for v in vals) / len(vals)
            eq *= beat
        n = max(1, len(view.live))
        bet_t, raise_t = ((0.60, 0.78), (0.48, 0.66), (0.40, 0.58))[min(n, 3) - 1]
        river = len(board) == 5
        pot = view.pot
        spr = view.stacks[view.me] / max(1, pot)
        can_raise = bool(view.responders) and not (river and evaluate(view.hole + board) == evaluate(board))
        if view.to_call == 0:
            if can_raise and eq >= bet_t:
                if spr <= 1.3 and eq >= 0.7:
                    return ("raise", view.max_to)
                return ("raise", view.bet + (0.75 if (eq >= 0.82 or river) else 0.55) * pot)
            return ("check", 0)
        mine_in = min(view.bet, view.max_to) - view.my_bet
        all_in_call = mine_in >= view.stacks[view.me]
        if can_raise and eq >= raise_t and not all_in_call:
            if spr <= 2.0 or eq >= 0.9:
                return ("raise", view.max_to)
            return ("raise", 2.8 * view.bet + 0.3 * pot)
        realize = 1.0 if (river or all_in_call) else 0.9
        return ("call", 0) if eq * realize >= mine_in / max(1, view.winnable(mine_in, {})) else ("fold", 0)
