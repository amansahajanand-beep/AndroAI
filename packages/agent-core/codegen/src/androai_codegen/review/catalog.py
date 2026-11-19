"""Curated knowledge about the Android ecosystem used by the review rules.

Everything here is *conservative by construction*: an entry is only added when the name really
requires an import (or a dependency) in ordinary code. A wrong entry would flag correct code, so
the lists favour precision over coverage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Names visible without an import. A project class with the same name in another package does not
# shadow these, so they are never reported as "missing import".
KOTLIN_DEFAULT_NAMES = frozenset(
    """Any Unit Nothing Int Long Short Byte Char Boolean Float Double Number String CharSequence
    Array IntArray LongArray ShortArray ByteArray CharArray BooleanArray FloatArray DoubleArray
    List MutableList Map MutableMap Set MutableSet Collection MutableCollection Iterable
    MutableIterable Iterator MutableIterator ListIterator Pair Triple Result Sequence Lazy
    Comparable Comparator Enum Annotation Throwable Exception Error RuntimeException
    IllegalArgumentException IllegalStateException IndexOutOfBoundsException
    UnsupportedOperationException ArithmeticException NumberFormatException
    NullPointerException ClassCastException AssertionError NoSuchElementException
    ConcurrentModificationException ArrayList HashMap HashSet LinkedHashMap LinkedHashSet
    StringBuilder Appendable Regex MatchResult Thread Runnable Class Object Math System Process
    Deprecated Suppress JvmStatic JvmField JvmOverloads JvmName JvmSuppressWildcards Volatile
    Synchronized Transient Strictfp Override Function Void Character Integer Cloneable Readable
    StackTraceElement InterruptedException CharRange IntRange LongRange ArrayDeque UInt ULong
    UShort UByte""".split()
)

JAVA_LANG_NAMES = frozenset(
    """Object String Integer Long Short Byte Character Boolean Float Double Number Math System
    Thread Runnable Exception RuntimeException Error Throwable IllegalArgumentException
    IllegalStateException NullPointerException IndexOutOfBoundsException ArithmeticException
    ClassCastException NumberFormatException UnsupportedOperationException InterruptedException
    AssertionError StringBuilder StringBuffer CharSequence Comparable Iterable Class Enum Void
    Override Deprecated SuppressWarnings FunctionalInterface SafeVarargs Cloneable Process
    ProcessBuilder Runtime StackTraceElement ThreadLocal Record AutoCloseable Appendable
    Readable ClassLoader SecurityException StrictMath""".split()
)

# package -> simple names that need an import from it. The order of packages matters: the first
# listed is the one suggested.
_PACKAGES: tuple[tuple[str, str], ...] = (
    (
        "androidx.compose.runtime",
        "Composable LaunchedEffect DisposableEffect SideEffect CompositionLocalProvider "
        "MutableState State Stable Immutable ReadOnlyComposable ProvidableCompositionLocal",
    ),
    ("androidx.compose.ui", "Modifier Alignment"),
    ("androidx.compose.ui.graphics", "Color Brush Shape ColorFilter"),
    ("androidx.compose.ui.layout", "ContentScale"),
    ("androidx.compose.ui.text", "TextStyle AnnotatedString SpanStyle"),
    ("androidx.compose.ui.text.font", "FontWeight FontFamily FontStyle"),
    ("androidx.compose.ui.text.style", "TextAlign TextOverflow TextDecoration"),
    (
        "androidx.compose.ui.text.input",
        "KeyboardType ImeAction PasswordVisualTransformation VisualTransformation TextFieldValue",
    ),
    ("androidx.compose.foundation.text", "KeyboardOptions KeyboardActions"),
    (
        "androidx.compose.ui.platform",
        "LocalContext LocalDensity LocalFocusManager LocalConfiguration "
        "LocalSoftwareKeyboardController LocalUriHandler ComposeView",
    ),
    ("androidx.compose.ui.unit", "Dp TextUnit IntOffset IntSize"),
    ("androidx.compose.ui.geometry", "Offset"),
    ("androidx.compose.ui.graphics.vector", "ImageVector"),
    ("androidx.compose.ui.tooling.preview", "Preview PreviewParameter PreviewParameterProvider"),
    (
        "androidx.compose.foundation.layout",
        "Column Row Box Spacer Arrangement PaddingValues BoxWithConstraints WindowInsets",
    ),
    ("androidx.compose.foundation", "Image Canvas BorderStroke ScrollState"),
    ("androidx.compose.foundation.lazy", "LazyColumn LazyRow LazyListState LazyListScope"),
    ("androidx.compose.foundation.lazy.grid", "LazyVerticalGrid GridCells LazyGridState"),
    ("androidx.compose.foundation.shape", "RoundedCornerShape CircleShape CutCornerShape"),
    ("androidx.compose.foundation.pager", "HorizontalPager VerticalPager PagerState"),
    (
        "androidx.compose.material3",
        "Text Button OutlinedButton TextButton IconButton Icon Scaffold TopAppBar "
        "FloatingActionButton ExtendedFloatingActionButton Card Surface MaterialTheme TextField "
        "OutlinedTextField Checkbox Switch RadioButton Slider CircularProgressIndicator "
        "LinearProgressIndicator Divider AlertDialog ListItem Snackbar SnackbarHost "
        "SnackbarHostState DropdownMenu DropdownMenuItem Tab TabRow Typography ButtonDefaults "
        "CardDefaults TextFieldDefaults BottomAppBar Badge BadgedBox Shapes",
    ),
    (
        "androidx.compose.material",
        "Text Button OutlinedButton TextButton IconButton Icon Scaffold TopAppBar "
        "FloatingActionButton ExtendedFloatingActionButton Card Surface MaterialTheme TextField "
        "OutlinedTextField Checkbox Switch RadioButton Slider CircularProgressIndicator "
        "LinearProgressIndicator Divider AlertDialog ListItem Snackbar SnackbarHost "
        "SnackbarHostState DropdownMenu DropdownMenuItem Tab TabRow Typography ButtonDefaults "
        "TextFieldDefaults BottomAppBar Badge BadgedBox Shapes BottomNavigation",
    ),
    (
        "androidx.compose.material3",
        "ExperimentalMaterial3Api CenterAlignedTopAppBar LargeTopAppBar MediumTopAppBar ElevatedCard "
        "OutlinedCard HorizontalDivider VerticalDivider NavigationBar NavigationBarItem "
        "NavigationRail ModalBottomSheet FilterChip AssistChip SuggestionChip InputChip ColorScheme "
        "ModalNavigationDrawer ModalDrawerSheet NavigationDrawerItem ExposedDropdownMenuBox",
    ),
    ("androidx.compose.material.icons", "Icons"),
    ("androidx.activity", "ComponentActivity OnBackPressedCallback"),
    (
        "androidx.core.app",
        "ComponentActivity ActivityCompat NotificationCompat NotificationManagerCompat",
    ),
    ("androidx.appcompat.app", "AppCompatActivity AppCompatDelegate AlertDialog"),
    (
        "android.app",
        "Activity Application Service NotificationManager NotificationChannel PendingIntent AlertDialog Dialog ProgressDialog",
    ),
    (
        "androidx.fragment.app",
        "Fragment FragmentActivity FragmentManager FragmentTransaction DialogFragment",
    ),
    (
        "androidx.lifecycle",
        "ViewModel ViewModelProvider LiveData MutableLiveData Observer LifecycleOwner Lifecycle "
        "SavedStateHandle AndroidViewModel ViewModelStoreOwner LifecycleEventObserver "
        "DefaultLifecycleObserver",
    ),
    ("android.os", "Bundle Build Handler Looper Parcelable Environment SystemClock"),
    (
        "android.content",
        "Context Intent SharedPreferences BroadcastReceiver IntentFilter ContentValues ContentResolver DialogInterface",
    ),
    ("android.content.pm", "PackageManager"),
    ("android", "Manifest"),
    (
        "android.widget",
        "Toast TextView Button EditText ImageView ProgressBar LinearLayout FrameLayout RelativeLayout ListView Spinner SeekBar ArrayAdapter Switch CheckBox",
    ),
    (
        "android.view",
        "View ViewGroup LayoutInflater MenuItem Menu WindowManager Gravity MotionEvent KeyEvent",
    ),
    ("android.util", "Log AttributeSet"),
    ("android.net", "Uri NetworkCapabilities"),
    ("android.graphics", "Bitmap BitmapFactory Paint Rect Matrix Typeface"),
    ("android.text", "TextUtils Editable TextWatcher"),
    ("android.webkit", "WebView WebViewClient WebSettings WebChromeClient"),
    ("android.provider", "Settings MediaStore"),
    ("android.database", "Cursor"),
    ("android.database.sqlite", "SQLiteDatabase SQLiteOpenHelper"),
    ("androidx.core.content", "ContextCompat FileProvider"),
    ("androidx.core.view", "ViewCompat WindowCompat WindowInsetsCompat"),
    ("androidx.core.splashscreen", "SplashScreen"),
    (
        "androidx.recyclerview.widget",
        "RecyclerView LinearLayoutManager GridLayoutManager DiffUtil ListAdapter",
    ),
    ("androidx.constraintlayout.widget", "ConstraintLayout"),
    ("androidx.cardview.widget", "CardView"),
    (
        "androidx.navigation",
        "NavController NavHostController NavType NavBackStackEntry NavGraphBuilder NavOptions NavDestination",
    ),
    ("androidx.navigation.compose", "NavHost"),
    ("androidx.navigation.fragment", "NavHostFragment"),
    (
        "androidx.room",
        "Entity Dao Database PrimaryKey ColumnInfo Query Insert Update Delete Room RoomDatabase "
        "TypeConverter TypeConverters Embedded Relation ForeignKey Index OnConflictStrategy Transaction",
    ),
    (
        "kotlinx.coroutines",
        "CoroutineScope Dispatchers Job Deferred GlobalScope SupervisorJob CoroutineExceptionHandler "
        "CancellationException",
    ),
    ("kotlin.coroutines.cancellation", "CancellationException"),
    ("kotlinx.coroutines.sync", "Mutex Semaphore"),
    ("kotlinx.coroutines.channels", "Channel"),
    (
        "kotlinx.coroutines.flow",
        "Flow StateFlow MutableStateFlow SharedFlow MutableSharedFlow SharingStarted FlowCollector",
    ),
    ("retrofit2", "Retrofit Call Callback Response"),
    (
        "retrofit2.http",
        "GET POST PUT DELETE PATCH HEAD Path Query QueryMap Body Header Headers Field FieldMap "
        "FormUrlEncoded Multipart Part Url HTTP",
    ),
    ("retrofit2.converter.gson", "GsonConverterFactory"),
    ("retrofit2.converter.moshi", "MoshiConverterFactory"),
    (
        "okhttp3",
        "OkHttpClient Request Interceptor RequestBody ResponseBody Headers Cache Call Callback Response",
    ),
    ("okhttp3.logging", "HttpLoggingInterceptor"),
    ("com.google.gson", "Gson GsonBuilder"),
    ("com.google.gson.annotations", "SerializedName Expose"),
    ("com.google.gson.reflect", "TypeToken"),
    ("com.squareup.moshi", "Moshi JsonClass Json JsonAdapter"),
    ("kotlinx.serialization", "Serializable SerialName Contextual"),
    ("kotlinx.serialization.json", "Json JsonObject JsonElement JsonPrimitive"),
    (
        "java.io",
        "File IOException InputStream OutputStream BufferedReader InputStreamReader FileInputStream FileOutputStream Serializable",
    ),
    ("dagger", "Module Provides Binds Component Subcomponent"),
    ("dagger.hilt", "InstallIn EntryPoint"),
    ("dagger.hilt.android", "HiltAndroidApp AndroidEntryPoint"),
    ("dagger.hilt.android.lifecycle", "HiltViewModel"),
    ("dagger.hilt.android.qualifiers", "ApplicationContext ActivityContext"),
    ("dagger.hilt.components", "SingletonComponent"),
    ("javax.inject", "Inject Singleton Named Qualifier Provider"),
    ("coil.compose", "AsyncImage SubcomposeAsyncImage"),
    ("coil3.compose", "AsyncImage SubcomposeAsyncImage"),
    ("kotlinx.parcelize", "Parcelize"),
    (
        "androidx.work",
        "WorkManager Worker CoroutineWorker WorkerParameters Constraints OneTimeWorkRequest PeriodicWorkRequest ExistingWorkPolicy NetworkType",
    ),
    ("androidx.datastore.core", "DataStore"),
    ("java.net", "URL HttpURLConnection URI"),
    (
        "java.util",
        "Date Locale UUID Calendar Timer TimerTask Random Arrays Collections Objects Optional "
        "Scanner Properties LinkedList TreeMap TreeSet Stack Queue Deque PriorityQueue BitSet "
        "Currency TimeZone Base64",
    ),
    ("kotlin.random", "Random"),
    ("android.util", "Base64"),
    ("java.text", "SimpleDateFormat DecimalFormat NumberFormat"),
    (
        "java.time",
        "LocalDate LocalDateTime LocalTime Instant Duration ZoneId ZonedDateTime DayOfWeek Month Period",
    ),
    ("java.time.format", "DateTimeFormatter"),
    (
        "java.util.concurrent",
        "Executors ExecutorService TimeUnit ConcurrentHashMap CountDownLatch CompletableFuture Executor",
    ),
)

# Names that Java needs imported but Kotlin sees by default (kotlin.collections.* typealiases).
JAVA_UTIL_JAVA_ONLY = [
    "List",
    "ArrayList",
    "Map",
    "HashMap",
    "Set",
    "HashSet",
    "LinkedHashMap",
    "LinkedHashSet",
    "Iterator",
    "Collection",
    "Comparator",
]


def _build() -> dict[str, tuple[str, ...]]:
    table: dict[str, list[str]] = {}
    for package, names in _PACKAGES:
        for name in names.split():
            fqn = f"{package}.{name}"
            candidates = table.setdefault(name, [])
            if fqn not in candidates:
                candidates.append(fqn)
    return {name: tuple(c) for name, c in table.items()}


TYPE_IMPORTS: dict[str, tuple[str, ...]] = _build()
JAVA_ONLY_TYPE_IMPORTS: dict[str, tuple[str, ...]] = {
    name: (f"java.util.{name}",) for name in JAVA_UTIL_JAVA_ONLY
}


def type_candidates(name: str, language: str) -> tuple[str, ...]:
    """Imports that could provide ``name`` ('' if it is not in the catalog)."""
    if language == "kotlin":
        if name in KOTLIN_DEFAULT_NAMES:
            return ()
        return TYPE_IMPORTS.get(name, ())
    if name in JAVA_LANG_NAMES:
        return ()
    return TYPE_IMPORTS.get(name) or JAVA_ONLY_TYPE_IMPORTS.get(name, ())


# --- unqualified calls and extension members that need an import (Kotlin) -------------------


@dataclass(frozen=True)
class ImportPattern:
    label: str
    regex: re.Pattern[str]
    candidates: tuple[str, ...]
    compose_only: bool = False
    requires: re.Pattern[str] | None = None  # the file must also match this to apply
    # A bare call may instead be a member of an implicit receiver (``rule.apply { setContent {} }``),
    # which needs no import. Inside such a scope the call proves nothing.
    member_possible: bool = False


def _call(
    label: str,
    pattern: str,
    *candidates: str,
    compose_only: bool = False,
    requires: str | None = None,
    member_possible: bool = False,
) -> ImportPattern:
    return ImportPattern(
        label,
        re.compile(pattern),
        candidates,
        compose_only,
        re.compile(requires) if requires else None,
        member_possible,
    )


_RT = "androidx.compose.runtime"
_LAYOUT = "androidx.compose.foundation.layout"
_IS_MODIFIER_FILE = r"\bModifier\b"
_LAZY_FILE = (
    r"\b(?:LazyColumn|LazyRow|LazyVerticalGrid|LazyHorizontalGrid|LazyListScope|LazyGridScope)\b"
)

CALL_IMPORTS: tuple[ImportPattern, ...] = (
    _call("remember", r"(?<![\w.])remember\s*[({]", f"{_RT}.remember", compose_only=True),
    _call(
        "mutableStateOf",
        r"(?<![\w.])mutableStateOf\s*[(<]",
        f"{_RT}.mutableStateOf",
        compose_only=True,
    ),
    _call(
        "mutableIntStateOf",
        r"(?<![\w.])mutableIntStateOf\s*\(",
        f"{_RT}.mutableIntStateOf",
        compose_only=True,
    ),
    _call(
        "mutableStateListOf",
        r"(?<![\w.])mutableStateListOf\s*[(<]",
        f"{_RT}.mutableStateListOf",
        compose_only=True,
    ),
    _call(
        "derivedStateOf",
        r"(?<![\w.])derivedStateOf\s*\{",
        f"{_RT}.derivedStateOf",
        compose_only=True,
    ),
    _call(
        "rememberCoroutineScope",
        r"(?<![\w.])rememberCoroutineScope\s*\(",
        f"{_RT}.rememberCoroutineScope",
        compose_only=True,
    ),
    _call(
        "rememberSaveable",
        r"(?<![\w.])rememberSaveable\s*[({]",
        f"{_RT}.saveable.rememberSaveable",
        compose_only=True,
    ),
    _call("collectAsState", r"\.collectAsState\s*\(", f"{_RT}.collectAsState", compose_only=True),
    _call(
        "collectAsStateWithLifecycle",
        r"\.collectAsStateWithLifecycle\s*\(",
        "androidx.lifecycle.compose.collectAsStateWithLifecycle",
        compose_only=True,
    ),
    _call(
        "observeAsState",
        r"\.observeAsState\s*\(",
        f"{_RT}.livedata.observeAsState",
        compose_only=True,
    ),
    # Not compose_only: an Activity calling setContent {} may import no other Compose symbol.
    _call(
        "setContent",
        r"(?<![\w.])setContent\s*\{",
        "androidx.activity.compose.setContent",
        member_possible=True,
    ),
    _call(
        "viewModel",
        r"(?<![\w.])viewModel\s*(?:<[^>\n]*>\s*)?\(",
        "androidx.lifecycle.viewmodel.compose.viewModel",
        compose_only=True,
    ),
    _call(
        "hiltViewModel",
        r"(?<![\w.])hiltViewModel\s*(?:<[^>\n]*>\s*)?\(",
        "androidx.hilt.navigation.compose.hiltViewModel",
        "androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel",
        compose_only=True,
    ),
    _call(
        "rememberNavController",
        r"(?<![\w.])rememberNavController\s*\(",
        "androidx.navigation.compose.rememberNavController",
        compose_only=True,
    ),
    _call(
        "composable",
        r"(?<![\w.])composable\s*\(",
        "androidx.navigation.compose.composable",
        compose_only=True,
    ),
    _call(
        "stringResource",
        r"(?<![\w.])stringResource\s*\(",
        "androidx.compose.ui.res.stringResource",
        compose_only=True,
    ),
    _call(
        "painterResource",
        r"(?<![\w.])painterResource\s*\(",
        "androidx.compose.ui.res.painterResource",
        compose_only=True,
    ),
    _call(
        "colorResource",
        r"(?<![\w.])colorResource\s*\(",
        "androidx.compose.ui.res.colorResource",
        compose_only=True,
    ),
    _call(
        "dimensionResource",
        r"(?<![\w.])dimensionResource\s*\(",
        "androidx.compose.ui.res.dimensionResource",
        compose_only=True,
    ),
    _call(
        "items",
        r"(?<![\w.])items\s*\(",
        "androidx.compose.foundation.lazy.items",
        "androidx.compose.foundation.lazy.grid.items",
        compose_only=True,
        requires=_LAZY_FILE,
    ),
    _call(
        "itemsIndexed",
        r"(?<![\w.])itemsIndexed\s*\(",
        "androidx.compose.foundation.lazy.itemsIndexed",
        "androidx.compose.foundation.lazy.grid.itemsIndexed",
        compose_only=True,
        requires=_LAZY_FILE,
    ),
    _call(
        "rememberLazyListState",
        r"(?<![\w.])rememberLazyListState\s*\(",
        "androidx.compose.foundation.lazy.rememberLazyListState",
        compose_only=True,
    ),
    _call(
        "rememberScrollState",
        r"(?<![\w.])rememberScrollState\s*\(",
        "androidx.compose.foundation.rememberScrollState",
        compose_only=True,
    ),
    _call(
        "isSystemInDarkTheme",
        r"(?<![\w.])isSystemInDarkTheme\s*\(",
        "androidx.compose.foundation.isSystemInDarkTheme",
        compose_only=True,
    ),
    _call(
        "darkColorScheme",
        r"(?<![\w.])darkColorScheme\s*\(",
        "androidx.compose.material3.darkColorScheme",
        compose_only=True,
    ),
    _call(
        "lightColorScheme",
        r"(?<![\w.])lightColorScheme\s*\(",
        "androidx.compose.material3.lightColorScheme",
        compose_only=True,
    ),
    _call(
        "buildAnnotatedString",
        r"(?<![\w.])buildAnnotatedString\s*\{",
        "androidx.compose.ui.text.buildAnnotatedString",
        compose_only=True,
    ),
    _call("viewModelScope", r"(?<![\w.])viewModelScope\b", "androidx.lifecycle.viewModelScope"),
    _call("lifecycleScope", r"(?<![\w.])lifecycleScope\b", "androidx.lifecycle.lifecycleScope"),
    _call("repeatOnLifecycle", r"\.repeatOnLifecycle\s*\(", "androidx.lifecycle.repeatOnLifecycle"),
    _call(
        "findNavController",
        r"(?<![\w.])findNavController\s*\(",
        "androidx.navigation.fragment.findNavController",
    ),
    _call(
        "viewModels",
        r"\bby\s+viewModels\b",
        "androidx.fragment.app.viewModels",
        "androidx.activity.viewModels",
    ),
    _call(
        "activityViewModels",
        r"\bby\s+activityViewModels\b",
        "androidx.fragment.app.activityViewModels",
    ),
    _call("launch", r"\blaunch\s*\{", "kotlinx.coroutines.launch"),
    _call("async", r"\basync\s*\{", "kotlinx.coroutines.async"),
    _call("withContext", r"(?<![\w.])withContext\s*\(", "kotlinx.coroutines.withContext"),
    _call("delay", r"(?<![\w.])delay\s*\(", "kotlinx.coroutines.delay"),
    _call("runBlocking", r"(?<![\w.])runBlocking\s*[({]", "kotlinx.coroutines.runBlocking"),
    _call("flow", r"(?<![\w.])flow\s*\{", "kotlinx.coroutines.flow.flow"),
    _call("collectLatest", r"\.collectLatest\s*[({]", "kotlinx.coroutines.flow.collectLatest"),
    _call("stateIn", r"\.stateIn\s*\(", "kotlinx.coroutines.flow.stateIn"),
    _call("edit", r"\.edit\s*\{", "androidx.core.content.edit"),
)

# Modifier extension functions that live in packages and so need an import.
_MODIFIER_EXTENSIONS: tuple[tuple[str, str, bool], ...] = (
    # (name, package, may be called without arguments)
    ("padding", _LAYOUT, False),
    ("fillMaxSize", _LAYOUT, True),
    ("fillMaxWidth", _LAYOUT, True),
    ("fillMaxHeight", _LAYOUT, True),
    ("size", _LAYOUT, False),
    ("width", _LAYOUT, False),
    ("height", _LAYOUT, False),
    ("offset", _LAYOUT, False),
    ("aspectRatio", _LAYOUT, False),
    ("wrapContentSize", _LAYOUT, True),
    ("wrapContentWidth", _LAYOUT, True),
    ("wrapContentHeight", _LAYOUT, True),
    ("defaultMinSize", _LAYOUT, False),
    ("widthIn", _LAYOUT, False),
    ("heightIn", _LAYOUT, False),
    ("sizeIn", _LAYOUT, False),
    ("requiredSize", _LAYOUT, False),
    ("statusBarsPadding", _LAYOUT, True),
    ("navigationBarsPadding", _LAYOUT, True),
    ("systemBarsPadding", _LAYOUT, True),
    ("imePadding", _LAYOUT, True),
    ("background", "androidx.compose.foundation", False),
    ("border", "androidx.compose.foundation", False),
    ("clickable", "androidx.compose.foundation", False),
    ("combinedClickable", "androidx.compose.foundation", False),
    ("verticalScroll", "androidx.compose.foundation", False),
    ("horizontalScroll", "androidx.compose.foundation", False),
    ("selectable", "androidx.compose.foundation.selection", False),
    ("toggleable", "androidx.compose.foundation.selection", False),
    ("clip", "androidx.compose.ui.draw", False),
    ("alpha", "androidx.compose.ui.draw", False),
    ("shadow", "androidx.compose.ui.draw", False),
    ("rotate", "androidx.compose.ui.draw", False),
    ("scale", "androidx.compose.ui.draw", False),
    ("drawBehind", "androidx.compose.ui.draw", False),
    ("zIndex", "androidx.compose.ui", False),
    ("graphicsLayer", "androidx.compose.ui.graphics", False),
    ("testTag", "androidx.compose.ui.platform", False),
    ("semantics", "androidx.compose.ui.semantics", False),
    ("pointerInput", "androidx.compose.ui.input.pointer", False),
)

MODIFIER_EXTENSIONS: tuple[ImportPattern, ...] = tuple(
    ImportPattern(
        label=name,
        regex=re.compile(rf"\.{name}\s*\(" + (r"" if no_args else r"\s*[^)\s]")),
        candidates=(f"{package}.{name}",),
        compose_only=True,
        requires=re.compile(_IS_MODIFIER_FILE),
    )
    for name, package, no_args in _MODIFIER_EXTENSIONS
)

# Library import prefix -> (acceptable dependency groups, human name). Compose and the other
# libraries that arrive transitively through a BOM or another artifact are deliberately absent.
LIB_DEPENDENCIES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("retrofit2", ("com.squareup.retrofit2",), "Retrofit"),
    ("okhttp3", ("com.squareup.okhttp3", "com.squareup.retrofit2"), "OkHttp"),
    ("com.google.gson", ("com.google.code.gson", "com.squareup.retrofit2"), "Gson"),
    ("com.squareup.moshi", ("com.squareup.moshi", "com.squareup.retrofit2"), "Moshi"),
    ("androidx.room", ("androidx.room",), "Room"),
    ("androidx.navigation", ("androidx.navigation",), "Navigation"),
    ("androidx.datastore", ("androidx.datastore",), "DataStore"),
    ("androidx.work", ("androidx.work",), "WorkManager"),
    ("androidx.paging", ("androidx.paging",), "Paging"),
    ("dagger", ("com.google.dagger",), "Dagger/Hilt"),
    ("coil", ("io.coil-kt",), "Coil"),
    ("coil3", ("io.coil-kt.coil3",), "Coil 3"),
    ("com.google.firebase", ("com.google.firebase",), "Firebase"),
    ("io.ktor", ("io.ktor",), "Ktor"),
    ("com.bumptech.glide", ("com.github.bumptech.glide",), "Glide"),
    ("androidx.constraintlayout", ("androidx.constraintlayout",), "ConstraintLayout"),
    (
        "androidx.recyclerview",
        ("androidx.recyclerview", "com.google.android.material"),
        "RecyclerView",
    ),
    ("com.google.android.material", ("com.google.android.material",), "Material Components"),
    ("androidx.appcompat", ("androidx.appcompat", "com.google.android.material"), "AppCompat"),
)

# Integrations whose removal from a project is high-impact (payments and authentication).
SENSITIVE_DEPENDENCY_GROUPS = (
    "com.stripe",
    "com.razorpay",
    "com.android.billingclient",
    "com.braintreepayments",
    "com.paypal",
    "com.google.android.gms:play-services-wallet",
    "com.google.android.gms:play-services-auth",
    "com.google.firebase:firebase-auth",
    "com.firebaseui",
    "com.auth0",
    "net.openid",
    "androidx.credentials",
)

# Dependency-free Android permissions that are worth surfacing to a human reviewer.
DANGEROUS_PERMISSIONS = frozenset(
    """CAMERA RECORD_AUDIO READ_CONTACTS WRITE_CONTACTS READ_CALENDAR WRITE_CALENDAR
    ACCESS_FINE_LOCATION ACCESS_COARSE_LOCATION ACCESS_BACKGROUND_LOCATION READ_PHONE_STATE
    CALL_PHONE READ_SMS SEND_SMS RECEIVE_SMS READ_EXTERNAL_STORAGE WRITE_EXTERNAL_STORAGE
    READ_MEDIA_IMAGES READ_MEDIA_VIDEO READ_MEDIA_AUDIO BODY_SENSORS ACTIVITY_RECOGNITION
    READ_CALL_LOG WRITE_CALL_LOG MANAGE_EXTERNAL_STORAGE SYSTEM_ALERT_WINDOW""".split()
)

# Resource-name prefixes of library-provided resources: never reported as "unresolved".
LIBRARY_RESOURCE_PREFIXES = (
    "abc_",
    "material_",
    "mtrl_",
    "m3_",
    "design_",
    "appcompat_",
    "common_google_",
    "exo_",
    "notification_",
    "ic_mtrl_",
    "mr_",
    "preference_",
    "androidx_",
    "fragment_",
    "$",
)
# Individual library resources that have no telltale prefix: (type, name) -> Maven groups of the
# dependencies that provide it. Unlike the prefixes above these are only trusted when the project
# really declares one of the groups, so the same name without the dependency is still an error.
LIBRARY_RESOURCE_NAMES: dict[tuple[str, str], tuple[str, ...]] = {
    ("string", "appbar_scrolling_view_behavior"): ("com.google.android.material",),
    ("integer", "google_play_services_version"): ("com.google.android.gms",),
    ("id", "recycler_view"): ("androidx.preference", "androidx.leanback"),
    ("id", "select_dialog_listview"): ("androidx.appcompat",),
    ("style", "FragmentScenarioEmptyFragmentActivityTheme"): ("androidx.fragment",),
}
# Compared against the underscore form of a name (``Theme.Material3.X`` -> ``Theme_Material3_X``).
# A bare ``Theme_`` is NOT here: ``@style/Theme.MyApp`` is the app's own and must be defined.
LIBRARY_STYLE_PREFIXES = (
    "Theme_AppCompat",
    "Theme_Material",
    "Theme_Design",
    "Theme_Leanback",
    "Theme_SplashScreen",
    "Widget_",
    "TextAppearance_",
    "ThemeOverlay_",
    "Base_",
    "Platform_",
    "Animation_",
    "MaterialAlertDialog",
    "ShapeAppearance",
    "Preference",
    "CardView",
    "AlertDialog_",
    "Dialog",
)
