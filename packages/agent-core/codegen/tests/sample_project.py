"""A realistic, known-good Android project used as the review engine's false-positive guard.

It is hand-written to be valid (Compose + Material 3 + Navigation + Room + Retrofit, a version
catalog, a manifest, resources, a Java utility, a unit test). The reviewer must report nothing
for it; every other review test starts from a copy of it and breaks exactly one thing.
"""

from __future__ import annotations

PKG = "com/example/todo"
MAIN = f"app/src/main/java/{PKG}"

FILES: dict[str, str | bytes] = {
    "settings.gradle.kts": """pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "Todo"
include(":app")
""",
    "build.gradle.kts": """plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.android) apply false
    alias(libs.plugins.kotlin.compose) apply false
    alias(libs.plugins.ksp) apply false
}
""",
    "gradle/libs.versions.toml": """[versions]
agp = "8.7.3"
kotlin = "2.0.21"
coreKtx = "1.15.0"
lifecycleRuntimeKtx = "2.8.7"
activityCompose = "1.9.3"
composeBom = "2024.12.01"
navigationCompose = "2.8.5"
retrofit = "2.11.0"
room = "2.6.1"

[libraries]
androidx-core-ktx = { group = "androidx.core", name = "core-ktx", version.ref = "coreKtx" }
androidx-lifecycle-runtime-ktx = { group = "androidx.lifecycle", name = "lifecycle-runtime-ktx", version.ref = "lifecycleRuntimeKtx" }
androidx-activity-compose = { group = "androidx.activity", name = "activity-compose", version.ref = "activityCompose" }
androidx-compose-bom = { group = "androidx.compose", name = "compose-bom", version.ref = "composeBom" }
androidx-ui = { group = "androidx.compose.ui", name = "ui" }
androidx-ui-graphics = { group = "androidx.compose.ui", name = "ui-graphics" }
androidx-ui-tooling = { group = "androidx.compose.ui", name = "ui-tooling" }
androidx-ui-tooling-preview = { group = "androidx.compose.ui", name = "ui-tooling-preview" }
androidx-material3 = { group = "androidx.compose.material3", name = "material3" }
androidx-navigation-compose = { group = "androidx.navigation", name = "navigation-compose", version.ref = "navigationCompose" }
retrofit-core = { group = "com.squareup.retrofit2", name = "retrofit", version.ref = "retrofit" }
retrofit-gson = { group = "com.squareup.retrofit2", name = "converter-gson", version.ref = "retrofit" }
androidx-room-runtime = { group = "androidx.room", name = "room-runtime", version.ref = "room" }
androidx-room-compiler = { group = "androidx.room", name = "room-compiler", version.ref = "room" }
junit = { group = "junit", name = "junit", version = "4.13.2" }

[plugins]
android-application = { id = "com.android.application", version.ref = "agp" }
kotlin-android = { id = "org.jetbrains.kotlin.android", version.ref = "kotlin" }
kotlin-compose = { id = "org.jetbrains.kotlin.plugin.compose", version.ref = "kotlin" }
ksp = { id = "com.google.devtools.ksp", version = "2.0.21-1.0.28" }
""",
    "app/build.gradle.kts": """plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.ksp)
}

android {
    namespace = "com.example.todo"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.example.todo"
        minSdk = 24
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    kotlinOptions {
        jvmTarget = "11"
    }
    buildFeatures {
        compose = true
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.ui)
    implementation(libs.androidx.ui.graphics)
    implementation(libs.androidx.ui.tooling.preview)
    implementation(libs.androidx.material3)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.retrofit.core)
    implementation(libs.retrofit.gson)
    implementation(libs.androidx.room.runtime)
    ksp(libs.androidx.room.compiler)
    testImplementation(libs.junit)
    debugImplementation(libs.androidx.ui.tooling)
}
""",
    "app/src/main/AndroidManifest.xml": """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">

    <uses-permission android:name="android.permission.INTERNET" />

    <application
        android:allowBackup="true"
        android:icon="@mipmap/ic_launcher"
        android:label="@string/app_name"
        android:roundIcon="@mipmap/ic_launcher_round"
        android:supportsRtl="true"
        android:theme="@style/Theme.Todo">
        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:theme="@style/Theme.Todo">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
""",
    "app/src/main/res/values/strings.xml": """<resources>
    <string name="app_name">Todo</string>
    <string name="add_task">Add task</string>
    <string name="empty_list">Nothing to do</string>
</resources>
""",
    "app/src/main/res/values/themes.xml": """<resources>
    <style name="Theme.Todo" parent="android:Theme.Material.Light.NoActionBar" />
</resources>
""",
    "app/src/main/res/values/colors.xml": """<resources>
    <color name="purple_500">#FF6200EE</color>
    <color name="white">#FFFFFFFF</color>
</resources>
""",
    "app/src/main/res/mipmap-hdpi/ic_launcher.webp": b"\x00webp",
    "app/src/main/res/mipmap-hdpi/ic_launcher_round.webp": b"\x00webp",
    f"{MAIN}/MainActivity.kt": """package com.example.todo

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.example.todo.ui.TodoApp
import com.example.todo.ui.theme.TodoTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            TodoTheme {
                TodoApp()
            }
        }
    }
}
""",
    f"{MAIN}/ui/theme/Color.kt": """package com.example.todo.ui.theme

import androidx.compose.ui.graphics.Color

val Purple80 = Color(0xFFD0BCFF)
val PurpleGrey80 = Color(0xFFCCC2DC)
val Pink80 = Color(0xFFEFB8C8)
val Purple40 = Color(0xFF6650A4)
""",
    f"{MAIN}/ui/theme/Theme.kt": """package com.example.todo.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable

private val DarkColorScheme = darkColorScheme(
    primary = Purple80,
    secondary = PurpleGrey80,
    tertiary = Pink80
)

private val LightColorScheme = lightColorScheme(
    primary = Purple40
)

@Composable
fun TodoTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit
) {
    val colorScheme = if (darkTheme) DarkColorScheme else LightColorScheme

    MaterialTheme(
        colorScheme = colorScheme,
        content = content
    )
}
""",
    f"{MAIN}/data/Task.kt": """package com.example.todo.data

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "tasks")
data class Task(
    @PrimaryKey(autoGenerate = true) val id: Int = 0,
    val title: String,
    val done: Boolean = false
)
""",
    f"{MAIN}/data/TaskDao.kt": """package com.example.todo.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface TaskDao {
    @Query("SELECT * FROM tasks ORDER BY id DESC")
    fun observeAll(): Flow<List<Task>>

    @Insert
    suspend fun insert(task: Task)
}
""",
    f"{MAIN}/data/AppDatabase.kt": """package com.example.todo.data

import androidx.room.Database
import androidx.room.RoomDatabase

@Database(entities = [Task::class], version = 1, exportSchema = false)
abstract class AppDatabase : RoomDatabase() {
    abstract fun taskDao(): TaskDao
}
""",
    f"{MAIN}/data/Api.kt": """package com.example.todo.data

import retrofit2.http.GET

interface Api {
    @GET("tips")
    suspend fun tips(): List<String>
}
""",
    f"{MAIN}/ui/TodoViewModel.kt": """package com.example.todo.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.todo.data.Task
import com.example.todo.data.TaskDao
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

class TodoViewModel(private val dao: TaskDao) : ViewModel() {
    val tasks: StateFlow<List<Task>> = dao.observeAll()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    fun add(title: String) {
        viewModelScope.launch { dao.insert(Task(title = title)) }
    }
}
""",
    f"{MAIN}/ui/TodoApp.kt": """package com.example.todo.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.example.todo.R

@Composable
fun TodoApp() {
    val navController = rememberNavController()
    NavHost(navController = navController, startDestination = "list") {
        composable("list") {
            ListScreen(onAdd = { navController.navigate("add") })
        }
        composable("add") {
            AddScreen(onDone = { navController.popBackStack() })
        }
    }
}

@Composable
fun ListScreen(onAdd: () -> Unit) {
    var count by remember { mutableStateOf(0) }
    Scaffold { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            Text(text = stringResource(R.string.app_name))
            Spacer(modifier = Modifier.height(8.dp))
            LazyColumn {
                items(listOf("a", "b")) { item -> Text(item) }
            }
            Button(onClick = { count += 1; onAdd() }) {
                Icon(Icons.Default.Add, contentDescription = null)
                Text(stringResource(R.string.add_task))
            }
        }
    }
}

@Composable
fun AddScreen(onDone: () -> Unit) {
    Button(onClick = onDone) { Text(stringResource(R.string.add_task)) }
}
""",
    f"{MAIN}/util/Strings.java": """package com.example.todo.util;

import java.util.List;
import java.util.Locale;

public final class Strings {
    private Strings() {}

    public static String join(List<String> parts) {
        StringBuilder out = new StringBuilder();
        for (String p : parts) {
            out.append(p.toUpperCase(Locale.ROOT)).append(',');
        }
        return out.toString();
    }
}
""",
    "app/src/test/java/com/example/todo/ExampleUnitTest.kt": """package com.example.todo

import org.junit.Assert.assertEquals
import org.junit.Test

class ExampleUnitTest {
    @Test
    fun addition_isCorrect() {
        assertEquals(4, 2 + 2)
    }
}
""",
}


def good_project() -> dict[str, str | bytes]:
    return dict(FILES)


def broken(edits: dict[str, tuple[str, str]]) -> dict[str, str | bytes]:
    """The good project with ``path -> (old, new)`` text replacements (each must match once)."""
    project = good_project()
    for path, (old, new) in edits.items():
        text = project[path]
        assert isinstance(text, str) and text.count(old) == 1, f"{path}: {old!r} must match once"
        project[path] = text.replace(old, new)
    return project


def with_files(base: dict[str, str | bytes], **_: object) -> dict[str, str | bytes]:
    return dict(base)
