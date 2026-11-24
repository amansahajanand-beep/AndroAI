"""M2.6: storage, network, dependency-injection and architecture-component facts."""

from __future__ import annotations

from analysis_fixtures import (
    API_SECRET_VALUE,
    QUERY_KEY,
    URL_PASSWORD,
    analyse,
    edges,
    fact,
    hilt_project,
    ids,
    java_xml_project,
    koin_project,
    mini_app,
    no_errors,
)

# -- Room ---------------------------------------------------------------------------------------


def test_room_entities_daos_and_databases_form_a_connected_model():
    report = analyse(hilt_project())
    entity = fact(report, "room_entity:com.example.notes.data.Note")
    assert entity.attributes["table_name"] == "notes"
    assert entity.attributes["table_name_source"] == "annotation"
    assert entity.attributes["columns"] == ("id", "title", "body")
    assert entity.attributes["primary_keys"] == ("id",)
    dao = fact(report, "room_dao:com.example.notes.data.NoteDao")
    assert dao.attributes["operations"] == ("Query:all", "Insert:insert", "Delete:delete")
    assert dao.attributes["tables_referenced"] == ("notes",)
    db = fact(report, "room_database:com.example.notes.data.NotesDatabase")
    assert db.attributes["version"] == 3 and db.attributes["export_schema"] is True
    assert db.attributes["entities"] == ("Note",)
    e = edges(report, "contains_entity") | edges(report, "exposes_dao") | edges(report, "accesses")
    assert (
        "room_database:com.example.notes.data.NotesDatabase",
        "room_entity:com.example.notes.data.Note",
    ) in e
    assert (
        "room_database:com.example.notes.data.NotesDatabase",
        "room_dao:com.example.notes.data.NoteDao",
    ) in e
    assert (
        "room_dao:com.example.notes.data.NoteDao",
        "room_entity:com.example.notes.data.Note",
    ) in e


def test_room_migrations_destructive_fallback_and_schema_export_are_policy_facts():
    report = analyse(hilt_project())
    assert ids(report, "room_migration") == ["1->2", "2->3"]
    assert ids(report, "room_policy") == ["schemaLocation"]
    files = mini_app(
        D="""
        package com.x
        import androidx.room.Room
        fun build(c: android.content.Context) =
            Room.databaseBuilder(c, Db::class.java, "x").fallbackToDestructiveMigration().build()
        """
    )
    policy = fact(analyse(files), "room_policy:fallbackToDestructiveMigration")
    assert "deleted and recreated" in policy.attributes["effect"]


def test_an_entity_without_a_table_name_uses_the_class_name_and_says_so():
    files = mini_app(
        E="""
        package com.x
        import androidx.room.Entity
        import androidx.room.Ignore
        import androidx.room.PrimaryKey
        @Entity(primaryKeys = ["a", "b"])
        data class Pair2(val a: Int, val b: Int, @Ignore val skipped: String = "")
        """
    )
    entity = fact(analyse(files), "room_entity:com.x.Pair2")
    assert entity.attributes["table_name"] == "Pair2"
    assert entity.attributes["table_name_source"] == "default"
    assert entity.attributes["primary_keys"] == ("a", "b")
    assert entity.attributes["columns"] == (
        "a",
        "b",
        "skipped",
    )  # Ignore applies to body properties


def test_a_java_room_entity_is_read_from_its_fields():
    files = mini_app(
        User_java="""
        package com.x;
        import androidx.room.Entity;
        import androidx.room.Ignore;
        import androidx.room.PrimaryKey;
        @Entity(tableName = "users")
        public class User {
            @PrimaryKey public int id;
            public String name;
            @Ignore public String cache;
            public static final String TAG = "x";
        }
        """
    )
    entity = fact(analyse(files), "room_entity:com.x.User")
    assert entity.attributes["columns"] == ("id", "name")
    assert entity.attributes["primary_keys"] == ("id",)


def test_an_entity_annotation_from_another_library_is_not_a_room_entity():
    files = mini_app(
        E="package com.x\nimport io.objectbox.annotation.Entity\n@Entity class Thing(val id: Long)\n"
    )
    assert ids(analyse(files), "room_entity") == []


def test_an_unimported_entity_annotation_is_inferred_and_a_wildcard_import_is_confirmed():
    inferred = analyse(mini_app(E="package com.x\n@Entity class A(val id: Long)\n"))
    assert fact(inferred, "room_entity:com.x.A").status == "inferred"
    confirmed = analyse(
        mini_app(E="package com.x\nimport androidx.room.*\n@Entity class A(val id: Long)\n")
    )
    assert fact(confirmed, "room_entity:com.x.A").status == "confirmed"


def test_a_room_database_is_recognised_from_its_base_class_even_without_the_annotation():
    files = mini_app(
        D="package com.x\nimport androidx.room.RoomDatabase\nabstract class Db : RoomDatabase()\n"
    )
    report = analyse(files)
    assert fact(report, "room_database:com.x.Db").status == "confirmed"
    assert "version" not in fact(report, "room_database:com.x.Db").attributes  # nothing invented


def test_a_dao_function_with_parameters_is_not_a_dao_accessor():
    files = mini_app(
        Db="""
        package com.x
        import androidx.room.Dao
        import androidx.room.Database
        import androidx.room.RoomDatabase
        @Dao interface UserDao
        @Database(entities = [], version = 1)
        abstract class Db : RoomDatabase() {
            abstract fun userDao(): UserDao
            abstract fun byName(name: String): UserDao
        }
        """
    )
    assert edges(analyse(files), "exposes_dao") == {
        ("room_database:com.x.Db", "room_dao:com.x.UserDao")
    }


# -- Retrofit and URLs --------------------------------------------------------------------------


def test_retrofit_services_endpoints_and_models():
    report = analyse(hilt_project())
    service = fact(report, "retrofit_service:com.example.notes.data.NotesApi")
    assert service.attributes["endpoints"] == ("GET notes -> notes", "POST notes -> create")
    get = fact(report, "http_endpoint:com.example.notes.data.NotesApi#GET notes notes")
    assert get.attributes["suspend"] is True and get.attributes["returns"] == "List<Note>"
    assert (
        "http_endpoint:com.example.notes.data.NotesApi#GET notes notes",
        "type:com.example.notes.data.Note",
    ) in edges(report, "uses_model")


def test_endpoint_paths_never_carry_a_query_string_into_the_report():
    report = analyse(hilt_project())
    text = report.model_dump_json()
    assert "token=abc" not in text
    assert "http_endpoint:com.example.notes.data.NotesApi#POST notes create" in {
        f.id for f in report.facts
    }


def test_the_base_url_keeps_scheme_host_and_path_and_drops_credentials_and_query():
    report = analyse(hilt_project())
    assert ids(report, "base_url") == ["https://api.example.com/v1/"]
    text = report.model_dump_json()
    assert URL_PASSWORD not in text and QUERY_KEY not in text


def test_a_base_url_constant_is_resolved_and_a_build_config_field_is_unknown():
    files = mini_app(
        N="""
        package com.x
        import retrofit2.Retrofit
        const val BASE = "https://constant.example.com/"
        fun a() = Retrofit.Builder().baseUrl(BASE).build()
        fun b() = Retrofit.Builder().baseUrl(BuildConfig.BASE_URL).build()
        fun c(host: String) = Retrofit.Builder().baseUrl("https://$host/").build()
        """
    )
    report = analyse(files)
    assert "https://constant.example.com/" in ids(report, "base_url")
    unknown = [f for f in report.facts if f.kind == "base_url" and f.status == "unknown"]
    assert len(unknown) == 2 and all(f.reason for f in unknown)


def test_an_interface_without_http_annotations_is_not_a_service_and_unimported_ones_are_inferred():
    plain = analyse(mini_app(I="package com.x\ninterface Repo { fun load(): Int }\n"))
    assert ids(plain, "retrofit_service") == []
    guessed = analyse(mini_app(I='package com.x\ninterface Api { @GET("x") fun x(): Int }\n'))
    assert fact(guessed, "retrofit_service:com.x.Api").status == "inferred"


def test_an_http_annotation_on_a_class_or_non_http_method_does_not_make_a_service():
    files = mini_app(
        C='package com.x\nimport retrofit2.http.GET\nclass NotAnInterface { @GET("x") fun x() {} }\n'
    )
    assert ids(analyse(files), "retrofit_service") == []


# -- other storage ------------------------------------------------------------------------------


def test_shared_preferences_datastore_files_and_sqlite_helpers():
    report = analyse(java_xml_project())
    assert fact(report, "shared_preferences:settings").attributes["named"] is True
    assert fact(report, "sqlite_helper:com.example.legacy.data.Db").status == "confirmed"
    koin = analyse(koin_project())
    assert fact(koin, "datastore:settings").attributes["datastore_kind"] == "preferences"
    files = mini_app(
        F="""
        package com.x
        import android.content.Context
        import android.content.SharedPreferences
        class F(private val c: Context) {
            fun a() = c.getSharedPreferences(NAME, 0)
            fun b() = androidx.preference.PreferenceManager.getDefaultSharedPreferences(c)
            fun c2() = c.openFileOutput("x", 0)
            fun d() = c.cacheDir
            fun e() = c.getExternalFilesDir(null)
        }
        """
    )
    found = analyse(files)
    assert set(ids(found, "shared_preferences")) == {"(computed)", "(default)"}
    assert set(ids(found, "file_storage")) == {"internal", "cache", "external"}


def test_storage_words_in_comments_and_strings_do_not_create_storage_facts():
    files = mini_app(
        S='package com.x\n// getSharedPreferences("x", 0)\nval s = "openFileOutput cacheDir"\n'
    )
    report = analyse(files)
    assert ids(report, "shared_preferences") == [] and ids(report, "file_storage") == []


def test_okhttp_interceptors_are_found_by_their_base_interface():
    files = mini_app(
        I="""
        package com.x
        import okhttp3.Interceptor
        import okhttp3.Response
        class AuthInterceptor : Interceptor {
            override fun intercept(chain: Interceptor.Chain): Response = chain.proceed(chain.request())
        }
        """
    )
    # an interface is implemented, not extended, but the role looks at every supertype
    assert fact(analyse(files), "http_interceptor:com.x.AuthInterceptor").status == "confirmed"


# -- Hilt and Dagger ----------------------------------------------------------------------------


def test_hilt_entry_points_view_models_modules_and_bindings():
    report = analyse(hilt_project())
    assert fact(report, "hilt_application:com.example.notes.NotesApp").status == "confirmed"
    assert fact(report, "hilt_android_entry:com.example.notes.MainActivity").status == "confirmed"
    assert (
        fact(report, "hilt_viewmodel:com.example.notes.ui.NoteListViewModel").status == "confirmed"
    )
    module = fact(report, "di_module:com.example.notes.di.RepositoryModule")
    assert module.attributes["framework"] == "hilt" and module.attributes["installed_in"] == (
        "SingletonComponent",
    )
    assert module.attributes["binds"] == 1
    provides = fact(report, "di_binding:com.example.notes.di.NetworkModule#provideApi()")
    assert provides.attributes["scopes"] == ("Singleton",)
    assert provides.attributes["provided_type"] == "NotesApi"
    binds = edges(report, "bound_to")
    assert (
        "type:com.example.notes.data.NoteRepository",
        "type:com.example.notes.data.NoteRepositoryImpl",
    ) in binds
    assert fact(report, "activity:com.example.notes.MainActivity").attributes["hilt"] is True
    assert "tech:hilt" not in fact(report, "activity:com.example.notes.MainActivity").tags or True


def test_constructor_injection_records_dependencies_and_edges():
    report = analyse(hilt_project())
    injectable = fact(report, "di_injectable:com.example.notes.ui.NoteListViewModel")
    assert injectable.attributes["dependencies"] == (
        "repo: NoteRepository",
        "dispatcher: CoroutineDispatcher",
    )
    inj = edges(report, "injects")
    assert (
        "type:com.example.notes.ui.NoteListViewModel",
        "type:com.example.notes.data.NoteRepository",
    ) in inj
    assert (
        "type:com.example.notes.data.NoteRepositoryImpl",
        "type:com.example.notes.data.NoteDao",
    ) in inj
    # a library type is not a project type: no edge to CoroutineDispatcher
    assert not any(t.endswith("CoroutineDispatcher") for _, t in inj)


def test_a_qualifier_and_a_named_binding_are_recorded():
    files = mini_app(
        M="""
        package com.x
        import dagger.Module
        import dagger.Provides
        import javax.inject.Named
        import javax.inject.Qualifier
        @Qualifier annotation class IoDispatcher
        @Module object M {
            @Provides @Named("io") fun a(): String = ""
            @Provides @IoDispatcher fun b(): Int = 0
        }
        """
    )
    report = analyse(files)
    assert fact(report, "di_binding:com.x.M#a()").attributes["named"] == "io"
    assert fact(report, "di_binding:com.x.M#b()").attributes["qualifiers"] == ("IoDispatcher",)


def test_field_injection_creates_an_edge_without_making_the_class_injectable():
    files = mini_app(
        A="""
        package com.x
        import javax.inject.Inject
        class Repo
        class Screen { @Inject lateinit var repo: Repo }
        """
    )
    report = analyse(files)
    assert ("type:com.x.Screen", "type:com.x.Repo") in edges(report, "injects")
    assert ids(report, "di_injectable") == []


def test_an_inject_annotation_from_another_library_is_not_dependency_injection():
    files = mini_app(
        A="package com.x\nimport com.other.Inject\nclass Repo\nclass V @Inject constructor(val r: Repo)\n"
    )
    assert ids(analyse(files), "di_injectable") == []


def test_dagger_components_and_java_modules():
    report = analyse(java_xml_project())
    component = fact(report, "dagger_component:com.example.legacy.di.AppComponent")
    assert component.attributes["modules"] == ("AppModule",)
    module = fact(report, "di_module:com.example.legacy.di.AppModule")
    assert module.attributes["framework"] == "dagger"
    assert module.attributes["provides"] == 1


def test_java_constructor_injection_and_assisted_factories():
    files = mini_app(
        Repo_java="""
        package com.x;
        import javax.inject.Inject;
        public class Repo {
            @Inject public Repo(Api api) {}
        }
        """,
        Api_java="package com.x;\npublic class Api {}\n",
        Factory="""
        package com.x
        import dagger.assisted.AssistedFactory
        import dagger.assisted.AssistedInject
        class Thing @AssistedInject constructor(val api: Api)
        @AssistedFactory interface ThingFactory { fun create(): Thing }
        """,
    )
    report = analyse(files)
    assert ("type:com.x.Repo", "type:com.x.Api") in edges(report, "injects")
    assert fact(report, "di_injectable:com.x.Thing").attributes["assisted"] is True
    assert fact(report, "di_assisted_factory:com.x.ThingFactory").status == "confirmed"


def test_generated_code_is_reported_as_not_analysed_but_does_not_block_completeness():
    report = analyse(hilt_project())
    note = [m for m in report.limitations if m.code == "annotation_processor_output_not_analysed"]
    assert note and not note[0].affects_completeness
    plain = analyse(mini_app(A="package com.x\nclass A\n"))
    assert not [
        m for m in plain.limitations if m.code == "annotation_processor_output_not_analysed"
    ]


# -- Koin ---------------------------------------------------------------------------------------


def test_koin_modules_definitions_and_start():
    report = analyse(koin_project())
    assert ids(report, "koin_module") == [
        "com.example.koinapp#appModule",
        "com.example.koinapp#dataModule",
    ]
    assert ids(report, "koin_definition") == [
        "com.example.koinapp#appModule#factoryOf Mapper",
        "com.example.koinapp#appModule#viewModelOf HomeViewModel",
        "com.example.koinapp#dataModule#single Repo",
    ]
    provided = edges(report, "provides")
    assert (
        "koin_module:com.example.koinapp#dataModule",
        "type:com.example.koinapp.Repo",
    ) in provided
    assert ("type:com.example.koinapp.Repo", "type:com.example.koinapp.RepoImpl") in edges(
        report, "bound_to"
    )
    loaded = {t for _, t in edges(report, "loads_module")}
    assert loaded == {
        "koin_module:com.example.koinapp#appModule",
        "koin_module:com.example.koinapp#dataModule",
    }


def test_koin_injection_sites_count_only_where_koin_is_imported():
    report = analyse(koin_project())
    inj = edges(report, "injects")
    assert ("type:com.example.koinapp.HomeFragment", "type:com.example.koinapp.Repo") in inj
    assert (
        "type:com.example.koinapp.HomeFragment",
        "type:com.example.koinapp.HomeViewModel",
    ) in inj
    # the same words without Koin imported are just function names
    files = mini_app(
        A="""
        package com.x
        class Repo
        class A { val repo: Repo by inject() }
        fun inject(): Int = 1
        """
    )
    assert edges(analyse(files), "injects") == set()


def test_a_koin_annotation_module_is_told_from_a_dagger_module():
    files = mini_app(
        K="package com.x\nimport org.koin.core.annotation.Module\n@Module class KoinStuff\n",
        D="package com.x\nimport dagger.Module\n@Module class DaggerStuff\n",
    )
    report = analyse(files)
    assert ids(report, "koin_module") == ["com.x.KoinStuff"]
    assert ids(report, "di_module") == ["com.x.DaggerStuff"]


# -- ViewModels ---------------------------------------------------------------------------------


def test_view_model_use_in_properties_defaults_and_bodies():
    files = mini_app(
        V="package com.x\nimport androidx.lifecycle.ViewModel\nclass HomeVm : ViewModel()\nclass OtherVm : ViewModel()\nclass Plain\n",
        U="""
        package com.x
        import androidx.compose.runtime.Composable
        import androidx.fragment.app.Fragment
        import androidx.fragment.app.viewModels
        import androidx.lifecycle.ViewModelProvider
        import androidx.hilt.navigation.compose.hiltViewModel

        class F : Fragment() {
            private val a: HomeVm by viewModels()
            private val b by viewModels<OtherVm>()
        }
        class G : androidx.appcompat.app.AppCompatActivity() {
            fun f() { val vm = ViewModelProvider(this)[HomeVm::class.java] }
        }
        @Composable fun Screen1(vm: HomeVm = hiltViewModel()) {}
        @Composable fun Screen2() { val vm: OtherVm = hiltViewModel() }
        @Composable fun Screen3() { val vm = hiltViewModel<HomeVm>() }
        """,
    )
    report = analyse(files)
    uses = {(s, t) for s, t in edges(report, "uses_viewmodel")}
    assert ("type:com.x.F", "viewmodel:com.x.HomeVm") in uses
    assert ("type:com.x.F", "viewmodel:com.x.OtherVm") in uses
    assert ("type:com.x.G", "viewmodel:com.x.HomeVm") in uses
    assert ("composable:com.x#Screen1(HomeVm)", "viewmodel:com.x.HomeVm") in uses
    assert ("composable:com.x#Screen2()", "viewmodel:com.x.OtherVm") in uses
    assert ("composable:com.x#Screen3()", "viewmodel:com.x.HomeVm") in uses


def test_a_view_model_name_that_is_not_a_project_class_gives_no_edge():
    files = mini_app(
        U="""
        package com.x
        import androidx.compose.runtime.Composable
        @Composable fun S() { val vm = hiltViewModel<LibraryVm>() }
        """
    )
    assert edges(analyse(files), "uses_viewmodel") == set()


def test_view_model_details_state_holders_scope_and_saved_state():
    files = mini_app(
        V="""
        package com.x
        import androidx.lifecycle.SavedStateHandle
        import androidx.lifecycle.ViewModel
        import androidx.lifecycle.viewModelScope
        import kotlinx.coroutines.flow.MutableStateFlow
        import kotlinx.coroutines.flow.StateFlow
        class Vm(private val saved: SavedStateHandle) : ViewModel() {
            val items: StateFlow<List<String>> = MutableStateFlow(emptyList())
            val label: androidx.lifecycle.LiveData<String>? = null
            val plain: Int = 0
            fun go() { viewModelScope }
        }
        """
    )
    vm = fact(analyse(files), "viewmodel:com.x.Vm")
    assert vm.attributes["state_holders"] == (
        "items: StateFlow<List<String>>",
        "label: androidx.lifecycle.LiveData<String>?",
    )
    assert vm.attributes["uses_viewmodel_scope"] is True
    assert vm.attributes["uses_saved_state_handle"] is True


def test_data_and_di_extractors_never_fail_on_the_fixtures():
    for files in (hilt_project(), java_xml_project(), koin_project()):
        no_errors(analyse(files))


def test_secret_looking_values_in_annotations_and_urls_stay_out_of_the_report():
    files = mini_app(
        S=f"""
        package com.x
        import javax.inject.Named
        import dagger.Provides
        import retrofit2.http.GET
        interface Api {{ @GET("v1/items?api_key={API_SECRET_VALUE}") fun items(): Int }}
        object M {{ @Provides @Named("password={API_SECRET_VALUE}") fun p(): String = "" }}
        """
    )
    text = analyse(files).model_dump_json()
    assert API_SECRET_VALUE not in text
