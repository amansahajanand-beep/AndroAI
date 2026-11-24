"""Android projects for the analysis tests, written out as plain text.

Four projects, each small enough to read and complete enough to exercise a whole family of facts:

* ``hilt_project``   Kotlin, Compose, Hilt, Room, Retrofit, two modules, a version catalog.
* ``java_xml_project`` Java, XML layouts, View Binding, Fragments, Navigation XML, Dagger, Groovy.
* ``koin_project``   Kotlin, Koin, DataStore, ViewModels in Fragments.
* ``convention_project`` a build that hides its settings behind a convention plugin.

The secrets planted in them are made up and built from pieces, so no complete credential appears
in this file. ``SECRETS`` lists them; the safety tests assert that none reaches a report.
"""

from __future__ import annotations

from textwrap import dedent

from androai_codegen.analysis import AnalysisReport, analyse_mapping
from androai_codegen.analysis.store import UNEXPLAINED_NOTE, UNEXPLAINED_REASON

GOOGLE_KEY = "AIza" + "Sy" + "Z" * 33
GITHUB_TOKEN = "ghp_" + "a1B2c3D4" * 5
API_SECRET_VALUE = "s3cr3t" + "Value" + "9f8e7d"
URL_PASSWORD = "hunter" + "2pass"
QUERY_KEY = "q" + "ueryKey" + "12345abc"
SECRETS = (GOOGLE_KEY, GITHUB_TOKEN, API_SECRET_VALUE, URL_PASSWORD, QUERY_KEY)

# Secrets that travel in a URL *path* rather than in user info or a query string. None of them has
# a keyword or a vendor prefix to recognise it by; they are told apart by where they sit and by
# how they look.
TELEGRAM_SECRET = "AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
TELEGRAM_TOKEN = "123456789" + ":" + TELEGRAM_SECRET
SLACK_IDS = "T0A1B2C3D/B0E1F2G3H"
SLACK_SECRET = "x7Yq9LmN3pR5sT8vW1zA4bC6"
DISCORD_ID = "112233445566778899"
DISCORD_TOKEN = "kJ8sd7Hq2LmNpR5tV9xZ3bC6dF1gH4jK7mN0pQ2sT5vW8yA1cE3gI6kM9oQ2sU5w"
PATH_SECRETS = (
    TELEGRAM_TOKEN,
    TELEGRAM_SECRET,
    SLACK_IDS,
    SLACK_SECRET,
    DISCORD_ID,
    DISCORD_TOKEN,
)

ANDROID_NS = 'xmlns:android="http://schemas.android.com/apk/res/android"'
APP_NS = 'xmlns:app="http://schemas.android.com/apk/res-auto"'
TOOLS_NS = 'xmlns:tools="http://schemas.android.com/tools"'


def d(text: str) -> str:
    return dedent(text).lstrip("\n")


def mini_app(extra: dict[str, str] | None = None, **sources: str) -> dict[str, str]:
    """One module ``app`` (namespace ``com.x``). ``Name="..."`` becomes ``com/x/Name.kt``;
    a ``Name_java`` key becomes ``com/x/Name.java``."""
    files = {
        "settings.gradle.kts": 'include(":app")\n',
        "app/build.gradle.kts": 'plugins { id("com.android.application") }\nandroid { namespace = "com.x" }\n',
        "app/src/main/AndroidManifest.xml": f"<manifest {ANDROID_NS}><application/></manifest>",
    }
    for name, text in sources.items():
        stem, suffix = (
            (name.removesuffix("_java"), ".java") if name.endswith("_java") else (name, ".kt")
        )
        files[f"app/src/main/java/com/x/{stem}{suffix}"] = d(text)
    files.update(extra or {})
    return files


def analyse(files: dict[str, str], **kwargs) -> AnalysisReport:
    """Analyse an in-memory project. Fails if any extractor raised (the analyser itself would
    swallow that and only record an ``extractor_error`` limitation, which a test could miss)."""
    report = analyse_mapping(files, **kwargs)
    errors = [m for m in report.limitations if m.code == "extractor_error"]
    assert errors == [], errors
    unexplained = [
        item.id
        for item in (*report.facts, *report.relationships)
        if UNEXPLAINED_NOTE in (item.note or "")
        or UNEXPLAINED_REASON in (getattr(item, "reason", None) or "")
    ]
    assert unexplained == [], f"claims whose code forgot to say why: {unexplained[:5]}"
    return report


def ids(report: AnalysisReport, kind: str) -> list[str]:
    """Subjects of the facts of ``kind``, sorted."""
    return sorted(f.subject for f in report.facts if f.kind == kind)


def edges(report: AnalysisReport, kind: str) -> set[tuple[str, str]]:
    """``(source, target)`` ids of every relationship of ``kind``."""
    return {(r.source, r.target) for r in report.relationships if r.kind == kind}


def fact(report: AnalysisReport, fact_id: str):
    found = next((f for f in report.facts if f.id == fact_id), None)
    assert found is not None, f"no fact {fact_id!r}; have {[f.id for f in report.facts][:12]}..."
    return found


def no_errors(report: AnalysisReport) -> None:
    """No extractor failed: the handlers that keep one bad input from stopping the run never fired."""
    assert [m for m in report.limitations if m.code == "extractor_error"] == []


# ---------------------------------------------------------------------------------------------
# 1. Kotlin + Compose + Hilt + Room + Retrofit, two modules
# ---------------------------------------------------------------------------------------------

KT = "app/src/main/java/com/example/notes"
DATA = "core/data/src/main/java/com/example/notes/data"


def hilt_project() -> dict[str, str]:
    files: dict[str, str] = {}
    files["settings.gradle.kts"] = d("""
        rootProject.name = "Notes"
        include(":app", ":core:data")
        """)
    files["build.gradle.kts"] = d("""
        plugins {
            alias(libs.plugins.android.application) apply false
            alias(libs.plugins.android.library) apply false
            alias(libs.plugins.kotlin.android) apply false
        }
        """)
    files["gradle/libs.versions.toml"] = d("""
        [versions]
        agp = "8.7.3"
        kotlin = "2.0.21"
        ksp = "2.0.21-1.0.28"
        hilt = "2.52"
        room = "2.6.1"
        target-sdk = "35"

        [libraries]
        hilt-android = { module = "com.google.dagger:hilt-android", version.ref = "hilt" }
        hilt-compiler = { module = "com.google.dagger:hilt-android-compiler", version.ref = "hilt" }
        hilt-navigation-compose = "androidx.hilt:hilt-navigation-compose:1.2.0"
        room-runtime = { module = "androidx.room:room-runtime", version.ref = "room" }
        room-ktx = { module = "androidx.room:room-ktx", version.ref = "room" }
        room-compiler = { module = "androidx.room:room-compiler", version.ref = "room" }
        retrofit = "com.squareup.retrofit2:retrofit:2.11.0"
        retrofit-converter-gson = "com.squareup.retrofit2:converter-gson:2.11.0"
        compose-bom = "androidx.compose:compose-bom:2024.10.00"
        compose-material3 = { module = "androidx.compose.material3:material3" }
        navigation-compose = "androidx.navigation:navigation-compose:2.8.3"
        junit = "junit:junit:4.13.2"

        [plugins]
        android-application = { id = "com.android.application", version.ref = "agp" }
        android-library = { id = "com.android.library", version.ref = "agp" }
        kotlin-android = { id = "org.jetbrains.kotlin.android", version.ref = "kotlin" }
        kotlin-compose = { id = "org.jetbrains.kotlin.plugin.compose", version.ref = "kotlin" }
        ksp = { id = "com.google.devtools.ksp", version.ref = "ksp" }
        hilt = { id = "com.google.dagger.hilt.android", version.ref = "hilt" }
        """)
    files["app/build.gradle.kts"] = d("""
        plugins {
            alias(libs.plugins.android.application)
            alias(libs.plugins.kotlin.android)
            alias(libs.plugins.kotlin.compose)
            alias(libs.plugins.ksp)
            alias(libs.plugins.hilt)
        }

        android {
            namespace = "com.example.notes"
            compileSdk = 35

            defaultConfig {
                applicationId = "com.example.notes"
                minSdk = 26
                targetSdk = libs.versions.target.sdk.get().toInt()
            }
            buildFeatures {
                compose = true
            }
        }

        dependencies {
            implementation(project(":core:data"))
            implementation(libs.hilt.android)
            ksp(libs.hilt.compiler)
            implementation(libs.hilt.navigation.compose)
            implementation(platform(libs.compose.bom))
            implementation(libs.compose.material3)
            implementation(libs.navigation.compose)
            implementation("com.squareup.okhttp3:okhttp:4.12.0")
            testImplementation(libs.junit)
            testImplementation("androidx.room:room-testing:2.6.1")
        }
        """)
    files["core/data/build.gradle.kts"] = d("""
        plugins {
            alias(libs.plugins.android.library)
            alias(libs.plugins.kotlin.android)
            alias(libs.plugins.ksp)
        }

        android {
            namespace = "com.example.notes.data"
            compileSdk = 35
            defaultConfig {
                minSdk = 26
            }
        }

        ksp {
            arg("room.schemaLocation", "$projectDir/schemas")
        }

        dependencies {
            implementation(libs.room.runtime)
            implementation(libs.room.ktx)
            ksp(libs.room.compiler)
            implementation(libs.retrofit)
            implementation(libs.retrofit.converter.gson)
        }
        """)
    files["app/src/main/AndroidManifest.xml"] = d(f"""
        <?xml version="1.0" encoding="utf-8"?>
        <manifest {ANDROID_NS}>
            <uses-permission android:name="android.permission.INTERNET" />
            <application
                android:name=".NotesApp"
                android:allowBackup="true"
                android:usesCleartextTraffic="false"
                android:theme="@style/Theme.Notes">
                <meta-data android:name="com.google.android.geo.API_KEY" android:value="{GOOGLE_KEY}" />
                <meta-data android:name="com.example.notes.MODE" android:value="demo" />
                <activity android:name=".MainActivity" android:exported="true">
                    <intent-filter>
                        <action android:name="android.intent.action.MAIN" />
                        <category android:name="android.intent.category.LAUNCHER" />
                    </intent-filter>
                    <intent-filter>
                        <action android:name="android.intent.action.VIEW" />
                        <data android:scheme="https" android:host="notes.example.com" android:pathPrefix="/n" />
                    </intent-filter>
                </activity>
                <service android:name=".sync.SyncService" android:exported="false" />
                <receiver android:name="com.example.notes.BootReceiver" android:exported="true">
                    <intent-filter>
                        <action android:name="android.intent.action.BOOT_COMPLETED" />
                    </intent-filter>
                </receiver>
            </application>
        </manifest>
        """)
    files["app/src/main/res/values/strings.xml"] = d("""
        <resources>
            <string name="app_name">Notes</string>
        </resources>
        """)
    files[f"{KT}/NotesApp.kt"] = d("""
        package com.example.notes

        import android.app.Application
        import dagger.hilt.android.HiltAndroidApp

        @HiltAndroidApp
        class NotesApp : Application()
        """)
    files[f"{KT}/MainActivity.kt"] = d("""
        package com.example.notes

        import android.os.Bundle
        import androidx.activity.ComponentActivity
        import androidx.activity.compose.setContent
        import androidx.compose.material3.Surface
        import com.example.notes.ui.NotesNavHost
        import com.example.notes.ui.theme.NotesTheme
        import dagger.hilt.android.AndroidEntryPoint

        @AndroidEntryPoint
        class MainActivity : ComponentActivity() {
            override fun onCreate(savedInstanceState: Bundle?) {
                super.onCreate(savedInstanceState)
                setContent {
                    NotesTheme {
                        Surface {
                            NotesNavHost()
                        }
                    }
                }
            }
        }
        """)
    files[f"{KT}/BootReceiver.kt"] = d("""
        package com.example.notes

        import android.content.BroadcastReceiver
        import android.content.Context
        import android.content.Intent

        class BootReceiver : BroadcastReceiver() {
            override fun onReceive(context: Context, intent: Intent) {}
        }
        """)
    files[f"{KT}/sync/SyncService.kt"] = d("""
        package com.example.notes.sync

        import android.app.Service
        import android.content.Intent

        class SyncService : Service() {
            override fun onBind(intent: Intent?) = null
        }
        """)
    files[f"{KT}/ui/NotesNavHost.kt"] = d("""
        package com.example.notes.ui

        import androidx.compose.runtime.Composable
        import androidx.navigation.compose.NavHost
        import androidx.navigation.compose.composable
        import androidx.navigation.compose.rememberNavController

        object Routes {
            const val LIST = "list"
        }

        @Composable
        fun NotesNavHost() {
            val navController = rememberNavController()
            NavHost(navController = navController, startDestination = Routes.LIST) {
                composable(Routes.LIST) {
                    NoteListScreen(onAdd = { navController.navigate("add") })
                }
                composable("add") {
                    AddNoteScreen()
                }
                composable("detail/{id}") {
                    NoteDetailScreen(navController)
                }
            }
        }
        """)
    files[f"{KT}/ui/NoteListScreen.kt"] = d("""
        package com.example.notes.ui

        import androidx.compose.runtime.Composable
        import androidx.compose.ui.tooling.preview.Preview
        import androidx.hilt.navigation.compose.hiltViewModel

        @Composable
        fun NoteListScreen(onAdd: () -> Unit, vm: NoteListViewModel = hiltViewModel()) {
        }

        @Preview
        @Composable
        private fun NoteListPreview() {
            NoteListScreen(onAdd = {})
        }
        """)
    files[f"{KT}/ui/AddNoteScreen.kt"] = d("""
        package com.example.notes.ui

        import androidx.compose.runtime.Composable

        @Composable
        fun AddNoteScreen() {
        }
        """)
    files[f"{KT}/ui/NoteDetailScreen.kt"] = d("""
        package com.example.notes.ui

        import androidx.compose.runtime.Composable
        import androidx.navigation.NavController

        @Composable
        fun NoteDetailScreen(navController: NavController) {
            navController.navigate("list")
        }
        """)
    files[f"{KT}/ui/Helpers.kt"] = d("""
        package com.example.notes.ui

        import androidx.compose.runtime.Composable

        @Composable
        fun Banner(text: String) {
        }
        """)
    files[f"{KT}/ui/theme/NotesTheme.kt"] = d("""
        package com.example.notes.ui.theme

        import androidx.compose.runtime.Composable

        @Composable
        fun NotesTheme(content: @Composable () -> Unit) {
            content()
        }
        """)
    files[f"{KT}/ui/NoteListViewModel.kt"] = d("""
        package com.example.notes.ui

        import androidx.lifecycle.ViewModel
        import androidx.lifecycle.viewModelScope
        import com.example.notes.data.Note
        import com.example.notes.data.NoteRepository
        import dagger.hilt.android.lifecycle.HiltViewModel
        import javax.inject.Inject
        import javax.inject.Named
        import kotlinx.coroutines.CoroutineDispatcher
        import kotlinx.coroutines.flow.MutableStateFlow
        import kotlinx.coroutines.flow.StateFlow
        import kotlinx.coroutines.launch

        @HiltViewModel
        class NoteListViewModel @Inject constructor(
            private val repo: NoteRepository,
            @Named("io") private val dispatcher: CoroutineDispatcher,
        ) : ViewModel() {
            private val _notes = MutableStateFlow<List<Note>>(emptyList())
            val notes: StateFlow<List<Note>> = _notes

            fun refresh() {
                viewModelScope.launch { }
            }
        }
        """)
    files[f"{KT}/di/RepositoryModule.kt"] = d("""
        package com.example.notes.di

        import com.example.notes.data.NoteRepository
        import com.example.notes.data.NoteRepositoryImpl
        import dagger.Binds
        import dagger.Module
        import dagger.hilt.InstallIn
        import dagger.hilt.components.SingletonComponent

        @Module
        @InstallIn(SingletonComponent::class)
        abstract class RepositoryModule {
            @Binds
            abstract fun bindRepository(impl: NoteRepositoryImpl): NoteRepository
        }
        """)
    files[f"{KT}/di/NetworkModule.kt"] = d(f"""
        package com.example.notes.di

        import com.example.notes.data.NotesApi
        import dagger.Module
        import dagger.Provides
        import dagger.hilt.InstallIn
        import dagger.hilt.components.SingletonComponent
        import javax.inject.Singleton
        import retrofit2.Retrofit
        import retrofit2.converter.gson.GsonConverterFactory

        @Module
        @InstallIn(SingletonComponent::class)
        object NetworkModule {{
            @Provides
            @Singleton
            fun provideApi(): NotesApi =
                Retrofit.Builder()
                    .baseUrl("https://svc:{URL_PASSWORD}@api.example.com/v1/?key={QUERY_KEY}")
                    .addConverterFactory(GsonConverterFactory.create())
                    .build()
                    .create(NotesApi::class.java)
        }}
        """)
    files[f"{DATA}/Note.kt"] = d("""
        package com.example.notes.data

        import androidx.room.Entity
        import androidx.room.PrimaryKey

        @Entity(tableName = "notes")
        data class Note(
            @PrimaryKey val id: Long,
            val title: String,
            val body: String,
        )
        """)
    files[f"{DATA}/NoteDao.kt"] = d("""
        package com.example.notes.data

        import androidx.room.Dao
        import androidx.room.Delete
        import androidx.room.Insert
        import androidx.room.Query
        import kotlinx.coroutines.flow.Flow

        @Dao
        interface NoteDao {
            @Query("SELECT * FROM notes ORDER BY id")
            fun all(): Flow<List<Note>>

            @Insert
            suspend fun insert(note: Note)

            @Delete
            suspend fun delete(note: Note)
        }
        """)
    files[f"{DATA}/NotesDatabase.kt"] = d("""
        package com.example.notes.data

        import androidx.room.Database
        import androidx.room.RoomDatabase

        @Database(entities = [Note::class], version = 3, exportSchema = true)
        abstract class NotesDatabase : RoomDatabase() {
            abstract fun noteDao(): NoteDao
        }
        """)
    files[f"{DATA}/Migrations.kt"] = d("""
        package com.example.notes.data

        import androidx.room.migration.Migration

        val MIGRATION_1_2 = Migration(1, 2)
        val MIGRATION_2_3 = Migration(2, 3)
        """)
    files[f"{DATA}/NotesApi.kt"] = d("""
        package com.example.notes.data

        import retrofit2.http.Body
        import retrofit2.http.GET
        import retrofit2.http.POST

        interface NotesApi {
            @GET("notes")
            suspend fun notes(): List<Note>

            @POST("notes?token=abc")
            suspend fun create(@Body note: Note): Note
        }
        """)
    files[f"{DATA}/NoteRepository.kt"] = d("""
        package com.example.notes.data

        import javax.inject.Inject

        interface NoteRepository {
            suspend fun load(): List<Note>
        }

        class NoteRepositoryImpl @Inject constructor(
            private val dao: NoteDao,
            private val api: NotesApi,
        ) : NoteRepository {
            override suspend fun load(): List<Note> = api.notes()
        }
        """)
    files["app/src/test/java/com/example/notes/NoteListViewModelTest.kt"] = d("""
        package com.example.notes

        import com.example.notes.ui.NoteListViewModel
        import org.junit.Test

        class NoteListViewModelTest {
            @Test
            fun `loads notes`() {}
        }
        """)
    return files


# ---------------------------------------------------------------------------------------------
# 2. Java + XML layouts + View Binding + Fragments + Navigation XML + Dagger, Groovy build
# ---------------------------------------------------------------------------------------------

JV = "app/src/main/java/com/example/legacy"
RES = "app/src/main/res"


def java_xml_project() -> dict[str, str]:
    files: dict[str, str] = {}
    files["settings.gradle"] = "rootProject.name = 'Legacy'\ninclude ':app'\n"
    files["build.gradle"] = d("""
        plugins {
            id 'com.android.application' version '8.5.2' apply false
        }
        """)
    files["app/build.gradle"] = d("""
        plugins {
            id 'com.android.application'
        }

        android {
            namespace 'com.example.legacy'
            compileSdk 34

            defaultConfig {
                applicationId "com.example.legacy"
                minSdk 21
                targetSdk 34
            }
            buildFeatures {
                viewBinding true
            }
        }

        dependencies {
            implementation 'androidx.appcompat:appcompat:1.6.1'
            implementation 'androidx.navigation:navigation-fragment:2.7.7'
            implementation 'androidx.recyclerview:recyclerview:1.3.2'
            implementation 'com.google.dagger:dagger:2.51'
            annotationProcessor 'com.google.dagger:dagger-compiler:2.51'
            testImplementation 'junit:junit:4.13.2'
        }
        """)
    files[f"{'app/src/main'}/AndroidManifest.xml"] = d(f"""
        <?xml version="1.0" encoding="utf-8"?>
        <manifest {ANDROID_NS}>
            <application android:name=".LegacyApp" android:theme="@style/AppTheme">
                <activity android:name=".MainActivity" android:exported="true">
                    <intent-filter>
                        <action android:name="android.intent.action.MAIN" />
                        <category android:name="android.intent.category.LAUNCHER" />
                    </intent-filter>
                </activity>
                <activity android:name=".LegacyActivity" android:exported="false" />
            </application>
        </manifest>
        """)
    files[f"{JV}/LegacyApp.java"] = d("""
        package com.example.legacy;

        import android.app.Application;

        public class LegacyApp extends Application {
        }
        """)
    files[f"{JV}/MainActivity.java"] = d("""
        package com.example.legacy;

        import android.os.Bundle;
        import androidx.appcompat.app.AppCompatActivity;
        import com.example.legacy.databinding.ActivityMainBinding;

        public class MainActivity extends AppCompatActivity {
            private ActivityMainBinding binding;

            @Override
            protected void onCreate(Bundle savedInstanceState) {
                super.onCreate(savedInstanceState);
                binding = ActivityMainBinding.inflate(getLayoutInflater());
                setContentView(binding.getRoot());
            }
        }
        """)
    files[f"{JV}/LegacyActivity.java"] = d("""
        package com.example.legacy;

        import android.os.Bundle;
        import androidx.appcompat.app.AppCompatActivity;
        import androidx.fragment.app.FragmentTransaction;
        import com.example.legacy.ui.DetailFragment;

        public class LegacyActivity extends AppCompatActivity {
            @Override
            protected void onCreate(Bundle savedInstanceState) {
                super.onCreate(savedInstanceState);
                setContentView(R.layout.activity_legacy);
                getSupportFragmentManager().beginTransaction()
                        .replace(R.id.container, new DetailFragment())
                        .commit();
            }
        }
        """)
    files[f"{JV}/ui/HomeFragment.java"] = d("""
        package com.example.legacy.ui;

        import androidx.fragment.app.Fragment;
        import com.example.legacy.R;

        public class HomeFragment extends Fragment {
            public HomeFragment() {
                super(R.layout.fragment_home);
            }
        }
        """)
    files[f"{JV}/ui/BaseFragment.java"] = d("""
        package com.example.legacy.ui;

        import androidx.fragment.app.Fragment;

        public abstract class BaseFragment extends Fragment {
        }
        """)
    files[f"{JV}/ui/DetailFragment.java"] = d("""
        package com.example.legacy.ui;

        public class DetailFragment extends BaseFragment {
        }
        """)
    files[f"{JV}/ui/ItemAdapter.java"] = d("""
        package com.example.legacy.ui;

        import androidx.recyclerview.widget.RecyclerView;

        public class ItemAdapter extends RecyclerView.Adapter<ItemAdapter.VH> {
            static class VH extends RecyclerView.ViewHolder {
                VH(android.view.View v) { super(v); }
            }
        }
        """)
    files[f"{JV}/ui/CounterView.java"] = d("""
        package com.example.legacy.ui;

        import android.content.Context;
        import android.view.View;

        public class CounterView extends View {
            public CounterView(Context context) { super(context); }
        }
        """)
    files[f"{JV}/data/Db.java"] = d("""
        package com.example.legacy.data;

        import android.database.sqlite.SQLiteOpenHelper;

        public abstract class Db extends SQLiteOpenHelper {
        }
        """)
    files[f"{JV}/data/Prefs.java"] = d("""
        package com.example.legacy.data;

        import android.content.Context;
        import android.content.SharedPreferences;

        public class Prefs {
            private final SharedPreferences prefs;
            public Prefs(Context context) {
                prefs = context.getSharedPreferences("settings", Context.MODE_PRIVATE);
            }
        }
        """)
    files[f"{JV}/di/AppComponent.java"] = d("""
        package com.example.legacy.di;

        import dagger.Component;
        import javax.inject.Singleton;

        @Singleton
        @Component(modules = {AppModule.class})
        public interface AppComponent {
            void inject(com.example.legacy.MainActivity activity);
        }
        """)
    files[f"{JV}/di/AppModule.java"] = d("""
        package com.example.legacy.di;

        import com.example.legacy.data.Prefs;
        import dagger.Module;
        import dagger.Provides;
        import javax.inject.Singleton;

        @Module
        public class AppModule {
            @Provides
            @Singleton
            static Prefs providePrefs() {
                return null;
            }
        }
        """)
    files[f"{RES}/layout/activity_main.xml"] = d(f"""
        <?xml version="1.0" encoding="utf-8"?>
        <LinearLayout {ANDROID_NS} {APP_NS} {TOOLS_NS}
            android:layout_width="match_parent"
            android:layout_height="match_parent"
            tools:context=".MainActivity">
            <androidx.fragment.app.FragmentContainerView
                android:id="@+id/nav_host"
                android:name="androidx.navigation.fragment.NavHostFragment"
                app:navGraph="@navigation/nav_main"
                app:defaultNavHost="true" />
            <TextView android:id="@+id/title" android:layout_width="wrap_content" android:layout_height="wrap_content" />
        </LinearLayout>
        """)
    files[f"{RES}/layout/fragment_home.xml"] = d(f"""
        <?xml version="1.0" encoding="utf-8"?>
        <FrameLayout {ANDROID_NS}>
            <include layout="@layout/item_row" />
            <com.example.legacy.ui.CounterView android:id="@+id/counter" android:layout_width="wrap_content" android:layout_height="wrap_content" />
        </FrameLayout>
        """)
    files[f"{RES}/layout/item_row.xml"] = d(f"""
        <?xml version="1.0" encoding="utf-8"?>
        <TextView {ANDROID_NS} android:id="@+id/row_label" android:layout_width="match_parent" android:layout_height="wrap_content" />
        """)
    files[f"{RES}/layout/activity_legacy.xml"] = d(f"""
        <?xml version="1.0" encoding="utf-8"?>
        <FrameLayout {ANDROID_NS} android:id="@+id/container" android:layout_width="match_parent" android:layout_height="match_parent" />
        """)
    files[f"{RES}/layout-land/item_row.xml"] = d(f"""
        <?xml version="1.0" encoding="utf-8"?>
        <TextView {ANDROID_NS} android:id="@+id/row_label" android:layout_width="match_parent" android:layout_height="wrap_content" />
        """)
    files[f"{RES}/navigation/nav_main.xml"] = d(f"""
        <?xml version="1.0" encoding="utf-8"?>
        <navigation {ANDROID_NS} {APP_NS}
            android:id="@+id/nav_main"
            app:startDestination="@id/homeFragment">
            <fragment
                android:id="@+id/homeFragment"
                android:name="com.example.legacy.ui.HomeFragment"
                android:label="Home">
                <action android:id="@+id/action_home_to_detail" app:destination="@id/detailFragment" />
                <deepLink app:uri="https://legacy.example.com/home" />
            </fragment>
            <fragment
                android:id="@+id/detailFragment"
                android:name="com.example.legacy.ui.DetailFragment">
                <argument android:name="itemId" app:argType="integer" />
            </fragment>
        </navigation>
        """)
    return files


# ---------------------------------------------------------------------------------------------
# 3. Kotlin + Koin + DataStore, ViewModels in Fragments
# ---------------------------------------------------------------------------------------------

KOIN = "app/src/main/java/com/example/koinapp"


def koin_project() -> dict[str, str]:
    files: dict[str, str] = {}
    files["settings.gradle.kts"] = 'rootProject.name = "KoinApp"\ninclude(":app")\n'
    files["build.gradle.kts"] = (
        'plugins { id("com.android.application") version "8.7.3" apply false }\n'
    )
    files["app/build.gradle.kts"] = d("""
        plugins {
            id("com.android.application")
            id("org.jetbrains.kotlin.android")
        }

        android {
            namespace = "com.example.koinapp"
            compileSdk = 34
            defaultConfig {
                applicationId = "com.example.koinapp"
                minSdk = 24
                targetSdk = 34
            }
        }

        dependencies {
            implementation("io.insert-koin:koin-android:3.5.6")
            implementation("androidx.datastore:datastore-preferences:1.1.1")
            implementation("androidx.fragment:fragment-ktx:1.8.3")
            implementation("io.ktor:ktor-client-android:2.3.12")
        }
        """)
    files["app/src/main/AndroidManifest.xml"] = d(f"""
        <?xml version="1.0" encoding="utf-8"?>
        <manifest {ANDROID_NS}>
            <application android:name=".KoinApp">
                <activity android:name=".HostActivity" android:exported="true" />
            </application>
        </manifest>
        """)
    files[f"{KOIN}/KoinApp.kt"] = d("""
        package com.example.koinapp

        import android.app.Application
        import org.koin.android.ext.koin.androidContext
        import org.koin.core.context.startKoin

        class KoinApp : Application() {
            override fun onCreate() {
                super.onCreate()
                startKoin {
                    androidContext(this@KoinApp)
                    modules(appModule, dataModule)
                }
            }
        }
        """)
    files[f"{KOIN}/Modules.kt"] = d("""
        package com.example.koinapp

        import org.koin.core.module.dsl.factoryOf
        import org.koin.core.module.dsl.singleOf
        import org.koin.core.module.dsl.viewModelOf
        import org.koin.dsl.module

        val appModule = module {
            viewModelOf(::HomeViewModel)
            factoryOf(::Mapper)
        }

        val dataModule = module {
            single<Repo> { RepoImpl(get()) }
        }
        """)
    files[f"{KOIN}/Repo.kt"] = d("""
        package com.example.koinapp

        interface Repo {
            fun items(): List<String>
        }

        class RepoImpl(private val mapper: Mapper) : Repo {
            override fun items(): List<String> = emptyList()
        }

        class Mapper
        """)
    files[f"{KOIN}/HomeViewModel.kt"] = d("""
        package com.example.koinapp

        import androidx.lifecycle.ViewModel

        class HomeViewModel(private val repo: Repo) : ViewModel()
        """)
    files[f"{KOIN}/HomeFragment.kt"] = d("""
        package com.example.koinapp

        import androidx.fragment.app.Fragment
        import org.koin.android.ext.android.inject
        import org.koin.androidx.viewmodel.ext.android.viewModel

        class HomeFragment : Fragment() {
            private val vm: HomeViewModel by viewModel()
            private val repo: Repo by inject()
        }
        """)
    files[f"{KOIN}/HostActivity.kt"] = d("""
        package com.example.koinapp

        import androidx.appcompat.app.AppCompatActivity
        import androidx.fragment.app.commit

        class HostActivity : AppCompatActivity() {
            fun show() {
                supportFragmentManager.commit {
                    replace(R.id.host, HomeFragment())
                }
            }
        }
        """)
    files[f"{KOIN}/Settings.kt"] = d("""
        package com.example.koinapp

        import android.content.Context
        import androidx.datastore.preferences.preferencesDataStore

        val Context.settingsStore by preferencesDataStore(name = "settings")
        """)
    return files


# ---------------------------------------------------------------------------------------------
# 4. A build whose settings live in a convention plugin
# ---------------------------------------------------------------------------------------------


def convention_project() -> dict[str, str]:
    files: dict[str, str] = {}
    files["settings.gradle.kts"] = d("""
        pluginManagement {
            includeBuild("build-logic")
        }
        rootProject.name = "Conv"
        include(":app", ":feature:home")
        """)
    files["build.gradle.kts"] = "// root\n"
    files["build-logic/convention/src/main/kotlin/AndroidAppPlugin.kt"] = d("""
        package convention

        class AndroidAppPlugin
        """)
    files["app/build.gradle.kts"] = d("""
        plugins {
            id("conv.android.application")
        }

        android {
            namespace = "com.example.conv"
        }

        dependencies {
            implementation(project(":feature:home"))
            implementation(libs.some.library)
        }
        """)
    files["feature/home/build.gradle.kts"] = d("""
        plugins {
            id("conv.android.library")
        }

        android {
            namespace = "com.example.conv.home"
            compileSdk = rootProject.extra["sdk"] as Int
        }
        """)
    files["app/src/main/AndroidManifest.xml"] = d(f"""
        <?xml version="1.0" encoding="utf-8"?>
        <manifest {ANDROID_NS}>
            <application><activity android:name=".MainActivity" android:exported="true" /></application>
        </manifest>
        """)
    files["app/src/main/java/com/example/conv/MainActivity.kt"] = d("""
        package com.example.conv

        import androidx.appcompat.app.AppCompatActivity

        class MainActivity : AppCompatActivity()
        """)
    return files
